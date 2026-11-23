"""
src/level_1_ingestion/xades_signer.py
Moduł podpisu elektronicznego XAdES-BES oraz parsowania certyfikatów KSeF 2.0.
Zgodny ze specyfikacją techniczną Ministerstwa Finansów (CIRFMF/ksef-client-csharp)
oraz standardem ETSI TS 101 903 v1.3.2.
"""

import base64
import datetime
import hashlib
import uuid
from typing import Any, Dict, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from lxml import etree


def parse_certificate_info(cert_bytes: bytes) -> Dict[str, Any]:
    """
    Parsuje bajty certyfikatu X.509 (PEM lub DER) i zwraca słownik z metadanymi
    dla interfejsu użytkownika (UI) i audytu bezpieczeństwa.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_bytes)
    except Exception:
        try:
            cert = x509.load_der_x509_certificate(cert_bytes)
        except Exception as e:
            return {"error": f"Niepoprawny format certyfikatu: {str(e)}", "is_valid": False}

    subject_map: Dict[str, str] = {}
    for attr in cert.subject:
        subject_map[attr.oid._name] = str(attr.value)

    issuer_map: Dict[str, str] = {}
    for attr in cert.issuer:
        issuer_map[attr.oid._name] = str(attr.value)

    now = datetime.datetime.now(datetime.timezone.utc)
    is_valid = cert.not_valid_before_utc <= now <= cert.not_valid_after_utc

    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = hashlib.sha256(der_bytes).hexdigest().upper()

    return {
        "subject_cn": subject_map.get("commonName", ""),
        "subject_o": subject_map.get("organizationName", ""),
        "issuer_cn": issuer_map.get("commonName", ""),
        "serial_number": str(cert.serial_number),
        "valid_from": cert.not_valid_before_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "valid_to": cert.not_valid_after_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "is_valid": is_valid,
        "sha256_fingerprint": fingerprint,
    }


def validate_key_pair(
    cert_bytes: bytes,
    key_bytes: bytes,
    key_password: Optional[bytes] = None,
) -> Tuple[bool, str]:
    """
    Sprawdza, czy klucz prywatny pasuje do klucza publicznego w certyfikacie.
    """
    try:
        try:
            cert = x509.load_pem_x509_certificate(cert_bytes)
        except Exception:
            cert = x509.load_der_x509_certificate(cert_bytes)
    except Exception as e:
        return False, f"Błąd wczytywania certyfikatu: {e}"

    try:
        try:
            private_key = serialization.load_pem_private_key(key_bytes, password=key_password)
        except Exception:
            private_key = serialization.load_der_private_key(key_bytes, password=key_password)
    except Exception as e:
        return False, f"Błąd wczytywania klucza prywatnego: {e}"

    # Podpisz i zweryfikuj testową wiadomość
    test_msg = b"TaxPilot-KSeF-Validation"
    try:
        if isinstance(private_key, rsa.RSAPrivateKey):
            sig = private_key.sign(test_msg, padding.PKCS1v15(), hashes.SHA256())
            cert.public_key().verify(sig, test_msg, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            sig = private_key.sign(test_msg, ec.ECDSA(hashes.SHA256()))
            cert.public_key().verify(sig, test_msg, ec.ECDSA(hashes.SHA256()))
        else:
            return False, "Nieobsługiwany typ klucza (wymagany RSA lub ECDSA)."
    except Exception as e:
        return False, f"Klucz prywatny nie pasuje do certyfikatu: {e}"

    return True, "Klucz prywatny pasuje do certyfikatu."


def sign_ksef_auth_token_request(
    challenge: str,
    nip: str,
    cert_bytes: bytes,
    key_bytes: bytes,
    key_password: Optional[bytes] = None,
) -> bytes:
    """
    Tworzy i podpisuje dokument AuthTokenRequest w standardzie XAdES-BES (Enveloped)
    zgodnie z wymaganiami KSeF 2.0 (CIRFMF/ksef-client-csharp SignatureService).

    Zwraca bajty UTF-8 podpisanego dokumentu XML gotowego do wysyłki pod /auth/xades-signature.
    """
    # 1. Wczytanie certyfikatu i klucza prywatnego
    try:
        cert = x509.load_pem_x509_certificate(cert_bytes)
    except Exception:
        cert = x509.load_der_x509_certificate(cert_bytes)

    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=key_password)
    except Exception:
        private_key = serialization.load_der_private_key(key_bytes, password=key_password)

    is_rsa = isinstance(private_key, rsa.RSAPrivateKey)
    is_ec = isinstance(private_key, ec.EllipticCurvePrivateKey)
    if not (is_rsa or is_ec):
        raise ValueError("Obsługiwane są wyłącznie klucze RSA lub ECDSA.")

    sig_method_uri = (
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
        if is_rsa
        else "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
    )

    sig_uuid = uuid.uuid4().hex
    sig_id = f"Signature-{sig_uuid}"
    signed_props_id = f"SignedProperties-{sig_uuid}"

    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_b64 = base64.b64encode(cert_der).decode("ascii")
    cert_digest_b64 = base64.b64encode(hashlib.sha256(cert_der).digest()).decode("ascii")

    # W standardzie KSeF / CIRFMF używana jest reprezentacja RFC4514 lub string nazwy podmiotu
    issuer_name = cert.issuer.rfc4514_string()
    serial_number = str(cert.serial_number)

    # Czas UTC ISO 8601
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 2. Główny dokument AuthTokenRequest
    ns_auth = "http://ksef.mf.gov.pl/auth/token/2.0"
    nsmap = {
        None: ns_auth,
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsd": "http://www.w3.org/2001/XMLSchema",
    }
    root = etree.Element(f"{{{ns_auth}}}AuthTokenRequest", nsmap=nsmap)
    chal_elem = etree.SubElement(root, f"{{{ns_auth}}}Challenge")
    chal_elem.text = challenge

    ctx_elem = etree.SubElement(root, f"{{{ns_auth}}}ContextIdentifier")
    nip_elem = etree.SubElement(ctx_elem, f"{{{ns_auth}}}Nip")
    nip_elem.text = nip

    subj_elem = etree.SubElement(root, f"{{{ns_auth}}}SubjectIdentifierType")
    subj_elem.text = "certificateSubject"

    # Skrót dokumentu przed dołączeniem ds:Signature (transformacja enveloped-signature)
    root_c14n = etree.tostring(root, method="c14n", exclusive=True)
    root_digest_b64 = base64.b64encode(hashlib.sha256(root_c14n).digest()).decode("ascii")

    # 3. xades:QualifyingProperties
    ns_xades = "http://uri.etsi.org/01903/v1.3.2#"
    ns_ds = "http://www.w3.org/2000/09/xmldsig#"

    qual_props_xml = f"""<xades:QualifyingProperties xmlns:xades="{ns_xades}" xmlns:ds="{ns_ds}" Target="#{sig_id}">
  <xades:SignedProperties Id="{signed_props_id}">
    <xades:SignedSignatureProperties>
      <xades:SigningTime>{now_utc}</xades:SigningTime>
      <xades:SigningCertificate>
        <xades:Cert>
          <xades:CertDigest>
            <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
            <ds:DigestValue>{cert_digest_b64}</ds:DigestValue>
          </xades:CertDigest>
          <xades:IssuerSerial>
            <ds:X509IssuerName>{issuer_name}</ds:X509IssuerName>
            <ds:X509SerialNumber>{serial_number}</ds:X509SerialNumber>
          </xades:IssuerSerial>
        </xades:Cert>
      </xades:SigningCertificate>
    </xades:SignedSignatureProperties>
  </xades:SignedProperties>
</xades:QualifyingProperties>"""
    qual_props_elem = etree.fromstring(qual_props_xml.encode("utf-8"))

    signed_props_elem = qual_props_elem.find(f"{{{ns_xades}}}SignedProperties")
    signed_props_c14n = etree.tostring(signed_props_elem, method="c14n", exclusive=True)
    signed_props_digest_b64 = base64.b64encode(hashlib.sha256(signed_props_c14n).digest()).decode("ascii")

    # 4. ds:SignedInfo
    signed_info_xml = f"""<ds:SignedInfo xmlns:ds="{ns_ds}">
  <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>
  <ds:SignatureMethod Algorithm="{sig_method_uri}"/>
  <ds:Reference URI="">
    <ds:Transforms>
      <ds:Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
      <ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>
    </ds:Transforms>
    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
    <ds:DigestValue>{root_digest_b64}</ds:DigestValue>
  </ds:Reference>
  <ds:Reference URI="#{signed_props_id}" Type="http://uri.etsi.org/01903#SignedProperties">
    <ds:Transforms>
      <ds:Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>
    </ds:Transforms>
    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
    <ds:DigestValue>{signed_props_digest_b64}</ds:DigestValue>
  </ds:Reference>
</ds:SignedInfo>"""
    signed_info_elem = etree.fromstring(signed_info_xml.encode("utf-8"))
    signed_info_c14n = etree.tostring(signed_info_elem, method="c14n", exclusive=True)

    # 5. Podpisanie skanonizowanego SignedInfo
    if is_rsa:
        signature_bytes = private_key.sign(
            signed_info_c14n,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    else:
        signature_bytes = private_key.sign(
            signed_info_c14n,
            ec.ECDSA(hashes.SHA256()),
        )
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

    # 6. Złożenie kompletnego węzła ds:Signature
    sig_elem = etree.Element(f"{{{ns_ds}}}Signature", nsmap={"ds": ns_ds}, Id=sig_id)
    sig_elem.append(signed_info_elem)

    sig_val_elem = etree.SubElement(sig_elem, f"{{{ns_ds}}}SignatureValue")
    sig_val_elem.text = signature_b64

    key_info_elem = etree.SubElement(sig_elem, f"{{{ns_ds}}}KeyInfo")
    x509_data_elem = etree.SubElement(key_info_elem, f"{{{ns_ds}}}X509Data")
    x509_cert_elem = etree.SubElement(x509_data_elem, f"{{{ns_ds}}}X509Certificate")
    x509_cert_elem.text = cert_b64

    obj_elem = etree.SubElement(sig_elem, f"{{{ns_ds}}}Object")
    obj_elem.append(qual_props_elem)

    # 7. Dołączenie do korzenia dokumentu
    root.append(sig_elem)

    return etree.tostring(root, xml_declaration=True, encoding="utf-8")

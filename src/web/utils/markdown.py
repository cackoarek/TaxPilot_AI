"""
src/web/utils/markdown.py
Wysokiej jakości konwerter Markdown -> HTML dla widoków panelu TaxPilot AI.
Formatuje raporty księgowe, sumy roczne YTD, audyty podatkowe oraz sprawozdania
w czysty, responsywny kod HTML zgodny z Tailwind CSS.
"""
import re
from typing import List, Tuple
from markupsafe import Markup


def render_markdown(text: str) -> Markup:
    """
    Konwertuje markdown na bezpieczny i estetyczny kod HTML.
    Obsługuje:
    - Nagłówki (#, ##, ###, ####) ze zróżnicowaną typografią
    - Tabele Markdown (| kol 1 | kol 2 |) z wyrównaniem komórek i wyróżnieniem wiersza sum
    - Listy punktowane (- lub *) i numerowane (1.)
    - Poziome linie (---)
    - Bloki kodu (``` ... ```) oraz inline code (`kod`)
    - Pogrubienia (**tekst**), kursywę (*tekst*) i symbole specjalne (np. $\\rightarrow$ -> &rarr;)
    - Cytaty i alerty (> tekst)
    """
    if not text:
        return Markup("")

    # Zastąpienie symboli LaTeX np. $\rightarrow$ na encje HTML &rarr;
    text = text.replace(r"$\rightarrow$", "&rarr;").replace(r"\rightarrow", "&rarr;")

    # 1. Zabezpieczenie bloków kodu ``` ... ```
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(1))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"

    text = re.sub(r"```(?:\w+)?\n?(.*?)```", save_code_block, text, flags=re.DOTALL)

    # 2. Inline code `kod`
    def format_inline_code(match):
        content = match.group(1).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-[11px] font-mono border border-slate-200">{content}</code>'

    text = re.sub(r"`([^`]+)`", format_inline_code, text)

    # 3. Pogrubienia **tekst**
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-bold text-slate-900">\1</strong>', text)

    # 4. Kursywa *tekst* (pomijając gwiazdki list)
    text = re.sub(r"(?<!^)(?<!\n)(?<!\*)\*([^*]+?)\*(?!\*)", r'<em class="italic text-slate-700">\1</em>', text)

    # 5. Linki [tekst](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" class="text-blue-600 underline font-semibold hover:text-blue-800" target="_blank" rel="noopener">\1</a>',
        text
    )

    lines = text.split("\n")
    output_html: List[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].rstrip()
        line_stripped = line.strip()

        # Pusta linia
        if not line_stripped:
            i += 1
            continue

        # Pozioma linia (--- lub ***)
        if re.match(r"^[-*_]{3,}$", line_stripped):
            output_html.append('<hr class="my-5 border-slate-200">')
            i += 1
            continue

        # Sprawdzenie znacznika bloku kodu
        if line_stripped.startswith("__CODE_BLOCK_") and line_stripped.endswith("__"):
            try:
                idx = int(line_stripped.replace("__CODE_BLOCK_", "").replace("__", ""))
                code_content = code_blocks[idx]
                escaped_code = (
                    code_content.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                output_html.append(
                    f'<pre class="bg-slate-900 text-slate-100 p-4 rounded-xl text-xs overflow-x-auto font-mono my-3 border border-slate-800 leading-relaxed"><code>{escaped_code}</code></pre>'
                )
            except Exception:
                pass
            i += 1
            continue

        # Sprawdzenie tabeli Markdown (| col 1 | col 2 |)
        if line_stripped.startswith("|") and line_stripped.endswith("|") and i + 1 < n and "|" in lines[i + 1]:
            sep_candidate = lines[i + 1].strip()
            if sep_candidate.startswith("|") and sep_candidate.endswith("|"):
                sep_raw = [c.strip() for c in sep_candidate.strip("|").split("|")]
                if sep_raw and all(re.match(r"^:?-+:?$", c) for c in sep_raw if c):
                    # Rozpoznano nagłówek i separator
                    alignments = []
                    for c in sep_raw:
                        if c.startswith(":") and c.endswith(":"):
                            alignments.append("text-center")
                        elif c.endswith(":"):
                            alignments.append("text-right")
                        else:
                            alignments.append("text-left")

                    header_cells = [c.strip() for c in line_stripped.strip("|").split("|")]
                    table_rows = []
                    i += 2
                    while i < n:
                        row_line = lines[i].strip()
                        if not row_line or not (row_line.startswith("|") and row_line.endswith("|")):
                            break
                        cells = [c.strip() for c in row_line.strip("|").split("|")]
                        table_rows.append(cells)
                        i += 1

                    tbl_html = [
                        '<div class="overflow-x-auto my-4 rounded-xl border border-slate-200 shadow-2xs">',
                        '  <table class="w-full text-xs text-left divide-y divide-slate-200 bg-white border-collapse">',
                        '    <thead class="bg-slate-50 text-slate-600 font-bold uppercase text-[10px] tracking-wider">',
                        '      <tr>'
                    ]
                    for idx, h in enumerate(header_cells):
                        align = alignments[idx] if idx < len(alignments) else "text-left"
                        tbl_html.append(f'        <th class="p-3 {align} whitespace-nowrap">{h}</th>')
                    tbl_html.append('      </tr>')
                    tbl_html.append('    </thead>')
                    tbl_html.append('    <tbody class="divide-y divide-slate-100 font-mono text-xs">')

                    for row in table_rows:
                        # Wyróżnienie wiersza sumy rocznej / YTD
                        row_text = " ".join(row).upper()
                        is_sum_row = "SUMA" in row_text or "RAZEM" in row_text or "TOTAL" in row_text
                        tr_cls = "bg-slate-50/90 font-bold border-t-2 border-slate-300 text-slate-900" if is_sum_row else "hover:bg-slate-50/80 transition-colors text-slate-700"

                        tbl_html.append(f'      <tr class="{tr_cls}">')
                        for idx, cell in enumerate(row):
                            align = alignments[idx] if idx < len(alignments) else "text-left"
                            tbl_html.append(f'        <td class="p-3 {align} whitespace-nowrap">{cell}</td>')
                        tbl_html.append('      </tr>')

                    tbl_html.append('    </tbody>')
                    tbl_html.append('  </table>')
                    tbl_html.append('</div>')
                    output_html.append("\n".join(tbl_html))
                    continue

        # Sprawdzenie nagłówków Markdown (####, ###, ##, #)
        if line_stripped.startswith("#### "):
            output_html.append(f'<h4 class="font-bold text-slate-800 text-xs uppercase tracking-wider mt-4 mb-2">{line_stripped[5:]}</h4>')
            i += 1
            continue
        elif line_stripped.startswith("### "):
            output_html.append(f'<h3 class="font-bold text-slate-900 text-sm mt-5 mb-2 pb-1 border-b border-slate-100">{line_stripped[4:]}</h3>')
            i += 1
            continue
        elif line_stripped.startswith("## "):
            output_html.append(f'<h2 class="font-black text-slate-900 text-base mt-6 mb-3 flex items-center space-x-2">{line_stripped[3:]}</h2>')
            i += 1
            continue
        elif line_stripped.startswith("# "):
            output_html.append(f'<h1 class="font-black text-slate-900 text-lg mb-3 pb-2 border-b-2 border-slate-200">{line_stripped[2:]}</h1>')
            i += 1
            continue

        # Sprawdzenie cytatów (> cytat)
        if line_stripped.startswith("> "):
            quote_lines = []
            while i < n and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            output_html.append(
                f'<blockquote class="border-l-4 border-blue-500 pl-3.5 py-1.5 my-3 text-slate-600 bg-blue-50/40 rounded-r-lg text-xs italic leading-relaxed">{"<br>".join(quote_lines)}</blockquote>'
            )
            continue

        # Sprawdzenie listy punktowanej (- lub *)
        if line_stripped.startswith("- ") or line_stripped.startswith("* "):
            list_items = []
            while i < n and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                item_content = lines[i].strip()[2:]
                list_items.append(f'<li class="pl-1 text-slate-700">{item_content}</li>')
                i += 1
            output_html.append(f'<ul class="list-disc pl-5 space-y-1.5 my-2.5 text-xs text-slate-700 leading-relaxed">{"".join(list_items)}</ul>')
            continue

        # Sprawdzenie listy numerowanej (1. , 2. )
        num_match = re.match(r"^\d+\.\s+(.*)$", line_stripped)
        if num_match:
            num_items = []
            while i < n:
                m = re.match(r"^\d+\.\s+(.*)$", lines[i].strip())
                if not m:
                    break
                num_items.append(f'<li class="pl-1 text-slate-700">{m.group(1)}</li>')
                i += 1
            output_html.append(f'<ol class="list-decimal pl-5 space-y-1.5 my-2.5 text-xs text-slate-700 leading-relaxed">{"".join(num_items)}</ol>')
            continue

        # Zwykły akapit
        output_html.append(f'<p class="mb-2 text-xs text-slate-700 leading-relaxed">{line_stripped}</p>')
        i += 1

    return Markup("\n".join(output_html))

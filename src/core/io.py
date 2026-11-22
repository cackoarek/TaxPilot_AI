import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Optional, Union


def atomic_write_text(
    path: Union[Path, str],
    content: str,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
) -> Path:
    """
    Atomically writes string content to a file using a temporary file
    in the same directory, flushing, fsyncing, and os.replace (atomic rename).
    Optionally sets file permissions (e.g. 0o600) on the temporary file before replacement.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = target.parent / f".{target.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(temp_path, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            try:
                os.chmod(temp_path, mode)
            except OSError:
                pass
        os.replace(temp_path, target)
        return target
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_json(
    path: Union[Path, str],
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Optional[Callable[[Any], Any]] = None,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
) -> Path:
    """
    Atomically writes data as JSON to a file using a temporary file
    in the same directory, os.fsync, and os.replace.
    Optionally sets file permissions (e.g. 0o600) on the temporary file before replacement.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = target.parent / f".{target.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(temp_path, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii, default=default)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            try:
                os.chmod(temp_path, mode)
            except OSError:
                pass
        os.replace(temp_path, target)
        return target
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional, Union

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore


@contextmanager
def file_lock(
    path: Union[Path, str],
    timeout: float = 10.0,
    exclusive: bool = True,
):
    """
    Kontekstowy menedżer blokady plikowej (advisory file lock) oparty na fcntl.flock.
    Używa towarzyszącego pliku blokady (.{name}.lock) odpornego na podmiany inode przy atomic_write.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.lock"

    if fcntl is None:
        yield
        return

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    start_time = time.time()
    locked = False
    try:
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                locked = True
                break
            except (BlockingIOError, OSError):
                if time.time() - start_time >= timeout:
                    raise TimeoutError(f"Nie udało się uzyskać blokady pliku {lock_path} w ciągu {timeout}s")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_write_text_impl(
    target: Path,
    content: str,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
) -> Path:
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


def atomic_write_text(
    path: Union[Path, str],
    content: str,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
    lock: bool = False,
    lock_timeout: float = 10.0,
) -> Path:
    """
    Atomically writes string content to a file using a temporary file
    in the same directory, flushing, fsyncing, and os.replace (atomic rename).
    Optionally sets file permissions (e.g. 0o600) on the temporary file before replacement.
    Optionally acquires an advisory file lock during write.
    """
    target = Path(path)
    if lock:
        with file_lock(target, timeout=lock_timeout):
            return _atomic_write_text_impl(target, content, encoding, mode)
    return _atomic_write_text_impl(target, content, encoding, mode)


def _atomic_write_json_impl(
    target: Path,
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Optional[Callable[[Any], Any]] = None,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
) -> Path:
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


def atomic_write_json(
    path: Union[Path, str],
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Optional[Callable[[Any], Any]] = None,
    encoding: str = "utf-8",
    mode: Optional[int] = None,
    lock: bool = False,
    lock_timeout: float = 10.0,
) -> Path:
    """
    Atomically writes data as JSON to a file using a temporary file
    in the same directory, os.fsync, and os.replace.
    Optionally sets file permissions (e.g. 0o600) on the temporary file before replacement.
    Optionally acquires an advisory file lock during write.
    """
    target = Path(path)
    if lock:
        with file_lock(target, timeout=lock_timeout):
            return _atomic_write_json_impl(target, data, indent, ensure_ascii, default, encoding, mode)
    return _atomic_write_json_impl(target, data, indent, ensure_ascii, default, encoding, mode)

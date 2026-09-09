"""Where kint keeps its state.

Everything lives under KINT_HOME (default ~/.kint). That directory is outside
every path Sibyl's cap accounting walks (~/.sibyl-memory, $HERMES_HOME/sibyl,
$SIBYL_MEMORY_DB), and kint volunteers its own footprint back into that
accounting through the cap gate (see kint.capvol).
"""

from __future__ import annotations

import os
from pathlib import Path


def kint_home() -> Path:
    home = Path(os.environ.get("KINT_HOME", "~/.kint")).expanduser()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    return home


def session_key_path() -> Path:
    return kint_home() / "session.key"


def vault_cache_path(space_hex: str) -> Path:
    return kint_home() / f"vault-{space_hex[:16]}.aes"


def enrolment_path(space_hex: str) -> Path:
    return kint_home() / f"enrol-{space_hex[:16]}.json"


def recovery_path(space_hex: str) -> Path:
    return kint_home() / f"RECOVERY-{space_hex[:16]}.txt"


def head_path(space_hex: str) -> Path:
    return kint_home() / f"head-{space_hex[:16]}.json"


def watermark_path(space_hex: str) -> Path:
    return kint_home() / f"watermark-{space_hex[:16]}.json"


def mirror_path(space_hex: str) -> Path:
    return kint_home() / f"mirror-{space_hex[:16]}.json"


def epochs_dir(space_hex: str) -> Path:
    d = kint_home() / "epochs" / space_hex[:16]
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def lock_path(space_hex: str) -> Path:
    return kint_home() / f"head-{space_hex[:16]}.lock"


def log_path() -> Path:
    return kint_home() / "kint.log"


def footprint_bytes() -> int:
    """Total bytes kint keeps on disk, for cap volunteering."""
    total = 0
    home = kint_home()
    for p in home.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def sibyl_db_path() -> Path:
    """The Sibyl store kint wraps: SIBYL_MEMORY_DB or Sibyl's default."""
    return Path(os.environ.get("SIBYL_MEMORY_DB", "~/.sibyl-memory/memory.db")).expanduser()


def write_private(path: Path, data: bytes) -> None:
    """Write a file with mode 0600, atomically."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

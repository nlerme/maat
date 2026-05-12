from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def format_datetime(value: Any) -> str:
    """Format an ISO-like datetime for display in tables and headers."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    from datetime import datetime

    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.strftime("%d-%m-%Y @ %H:%M:%S")
        except ValueError:
            pass
    return text.replace("T", " @ ")


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return cleaned.strip("._") or "item"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def truncate_text(path: Path, max_bytes: int) -> tuple[str, bool]:
    if not path.exists():
        return "", False
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= max_bytes:
            data = handle.read()
            truncated = False
        else:
            handle.seek(max(0, size - max_bytes))
            data = handle.read(max_bytes)
            truncated = True
    return data.decode("utf-8", errors="replace"), truncated


def format_duration_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min {sec:02d} s"
    if minutes:
        return f"{minutes} min {sec:02d} s"
    return f"{sec} s"

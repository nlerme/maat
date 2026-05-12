#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maat_app.json_style import format_value_comment_json


def read_cpuinfo(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def cpu_counts(cpuinfo: str) -> tuple[int, int]:
    logical_threads = len(re.findall(r"^processor\s*:", cpuinfo, flags=re.MULTILINE))
    physical_pairs: set[tuple[str, str]] = set()
    current_physical = current_core = None
    for line in cpuinfo.splitlines() + [""]:
        if not line.strip():
            if current_physical is not None and current_core is not None:
                physical_pairs.add((current_physical, current_core))
            current_physical = current_core = None
        elif line.startswith("physical id"):
            current_physical = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            current_core = line.split(":", 1)[1].strip()
    physical_cores = len(physical_pairs) if physical_pairs else logical_threads
    return max(logical_threads, 1), max(physical_cores, 1)


def set_value(entry: dict[str, Any], value: Any) -> None:
    if isinstance(entry, dict) and "value" in entry:
        entry["value"] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-tune MAAT v11 parallelism settings from /proc/cpuinfo.")
    parser.add_argument("config", nargs="?", default="config.json")
    parser.add_argument("--cpuinfo", default="/proc/cpuinfo")
    args = parser.parse_args()
    root = Path(args.config).resolve().parent
    logical_threads, physical_cores = cpu_counts(read_cpuinfo(Path(args.cpuinfo)))
    queue_workers = max(1, min(4, physical_cores // 2 if physical_cores >= 4 else 1))
    config_path = Path(args.config)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    set_value(cfg.get("queue", {}).get("worker_count", {}), queue_workers)
    config_path.write_text(format_value_comment_json(cfg), encoding="utf-8")
    for profile_path in sorted((root / "languages").glob("*/language.json")):
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if isinstance(profile.get("compile_resources"), dict):
            profile["compile_resources"]["cpus"] = str(max(1, min(4, physical_cores)))
        if isinstance(profile.get("run_resources"), dict):
            per_worker = max(1, physical_cores // max(queue_workers, 1))
            profile["run_resources"]["cpus"] = str(max(1, min(4, per_worker)))
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MAAT v11 parallelism auto-tuned")
    print(f"  logical_threads={logical_threads}")
    print(f"  physical_cores={physical_cores}")
    print(f"  queue.worker_count={queue_workers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

from .config import load_config


def main() -> int:
    cfg = load_config()
    checks: list[tuple[str, bool, str]] = []
    for label, key in [("active_project", "active_project_abs"), ("data_dir", "data_dir_abs"), ("students_csv", "students_csv_abs")]:
        path = Path(cfg[key])
        checks.append((label, path.exists(), str(path)))
    data_dir = Path(cfg["data_dir_abs"])
    instances = sorted(data_dir.glob(str(cfg.get("public_instances_glob", "instance_*")))) if data_dir.exists() else []
    student_count = 0
    students_csv = Path(cfg["students_csv_abs"])
    if students_csv.exists():
        with students_csv.open("r", newline="", encoding="utf-8") as handle:
            student_count = sum(1 for _ in csv.DictReader(handle))
    for label, ok, detail in checks:
        print(f"[{ 'OK' if ok else 'KO' }] {label}: {detail}")
    print(f"[INFO] project: {cfg.get('project_id')} — {cfg.get('project_title')}")
    print(f"[INFO] languages: {', '.join(cfg.get('allowed_languages', []))}")
    print(f"[INFO] instances: {len(instances)}")
    print(f"[INFO] students: {student_count}")
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run([docker, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        print(f"[OK] docker: {result.stdout.strip()}")
    else:
        print("[KO] docker: not found")
    return 0 if all(ok for _, ok, _ in checks) and instances else 1


if __name__ == "__main__":
    raise SystemExit(main())

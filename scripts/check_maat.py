from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maat_app.config import load_config  # noqa: E402


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "OK" if passed else "FAIL"
    print(f"[{mark}] {name}{': ' + detail if detail else ''}")
    return passed


def warn(name: str, detail: str = "") -> None:
    print(f"[WARN] {name}{': ' + detail if detail else ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check MAAT configuration, project profiles, language profiles and Docker runners.")
    parser.add_argument("--strict", action="store_true", help="Return a failure if Docker is unavailable or a required runner image is missing.")
    parser.add_argument("--fix", action="store_true", help="Create safe missing runtime directories and .gitkeep files.")
    args = parser.parse_args(argv)

    checks: list[bool] = []
    print("=== configuration ===")
    try:
        cfg = load_config()
        checks.append(ok("configuration", True, f"project={cfg.get('project_id')} languages={','.join(cfg.get('allowed_languages', []))}"))
    except Exception as exc:
        ok("configuration", False, str(exc))
        return 1

    print("\n=== project ===")
    checks.append(ok("active project", Path(cfg["active_project_abs"]).exists(), cfg["active_project_abs"]))
    checks.append(ok("project data", Path(cfg["data_dir_abs"]).exists(), cfg["data_dir_abs"]))
    instances = sorted(Path(cfg["data_dir_abs"]).glob(str(cfg.get("public_instances_glob", "instance_*"))))
    checks.append(ok("instances", bool(instances), f"{len(instances)} file(s)"))
    metric_names = [str(m.get("name")) for m in cfg.get("project_metrics", [])]
    checks.append(ok("metrics", bool(metric_names), ", ".join(metric_names)))

    print("\n=== languages and Docker ===")
    docker_available = shutil.which("docker") is not None and subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    if docker_available:
        ok("Docker daemon", True, "available")
    else:
        warn("Docker daemon", "unavailable in this environment; required for real evaluation")
        if args.strict:
            checks.append(False)
    for lang, profile in (cfg.get("language_profiles") or {}).items():
        checks.append(ok(f"language profile {lang}", True, profile.get("docker_image", "")))
        dockerfile = ROOT / "docker" / f"{lang}-runner" / "Dockerfile"
        checks.append(ok(f"Dockerfile {lang}", dockerfile.exists(), str(dockerfile)))
        image = str(profile.get("docker_image", ""))
        if docker_available and image:
            present = subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
            checks.append(ok(f"Docker image {lang}", present, image))
        elif args.strict:
            checks.append(False)

    print("\n=== runtime directories ===")
    runtime_dirs = {
        "submissions": ROOT / "submissions",
        "runs": ROOT / "runs",
        "logs": ROOT / "logs",
        "project documents": Path(cfg["documents_dir_abs"]),
        "project results": Path(cfg["results_dir_abs"]),
        "project snapshots": Path(cfg["snapshot_directory_abs"]),
    }
    for label, path in runtime_dirs.items():
        if args.fix:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".gitkeep").touch(exist_ok=True)
        checks.append(ok(f"directory {label}", path.exists(), str(path)))

    print("\n=== effective configuration ===")
    print(json.dumps({
        "project": cfg.get("project_id"),
        "title": cfg.get("project_title"),
        "languages": cfg.get("allowed_languages"),
        "metrics": metric_names,
        "data_dir": cfg.get("data_dir_abs"),
        "timer_enabled": cfg.get("session_timer_enabled"),
        "docker": {
            "network": cfg.get("docker_network"),
            "read_only_root_filesystem": cfg.get("docker_read_only_root_filesystem"),
            "container_user": cfg.get("docker_container_user"),
            "tmpfs": cfg.get("docker_tmpfs"),
        },
    }, ensure_ascii=False, indent=2))
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

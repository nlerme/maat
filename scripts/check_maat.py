from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maat_app.config import load_config  # noqa: E402
from maat_app.json_style import format_value_comment_json  # noqa: E402
from maat_app.profiles import validate_value_comment_file  # noqa: E402

RUNTIME_ROOTS = {"submissions", "runs", "logs"}
PROJECT_RUNTIME_RULES = {
    "documents": {".gitkeep", "students.xlsx"},
    "results": {".gitkeep"},
}
SECRET_PATTERNS = [
    re.compile(r"admin_token\"\s*:\s*\{\s*\"value\"\s*:\s*\"(?!CHANGE_ME\")[^\"]+\""),
    re.compile(r"ntfy_topic\"\s*:\s*\{\s*\"value\"\s*:\s*\"(?!CHANGE_ME\")[^\"]+\""),
]


def ok(name: str, passed: bool, detail: str = "") -> bool:
    mark = "OK" if passed else "FAIL"
    print(f"[{mark}] {name}{': ' + detail if detail else ''}")
    return passed


def warn(name: str, detail: str = "") -> None:
    print(f"[WARN] {name}{': ' + detail if detail else ''}")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def check_json_style(path: Path) -> bool:
    data = load_json(path)
    try:
        validate_value_comment_file(data, str(path))
    except Exception as exc:
        return ok(f"value/comment format {path}", False, str(exc))
    expected = format_value_comment_json(data)
    return ok(f"JSON layout {path}", path.read_text(encoding="utf-8") == expected, "section-level layout")


def public_release_check() -> int:
    checks: list[bool] = []
    print("=== public release hygiene ===")
    checks.append(ok("config.json absent", not (ROOT / "config.json").exists(), "only config.example.json must be versioned"))
    for required in ["README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md", "CONTRIBUTING.md", "VERSION", "config.example.json"]:
        checks.append(ok(f"required file {required}", (ROOT / required).exists()))
    checks.append(ok("no root ZIP bundles", not any(ROOT.glob("*.zip"))))

    print("\n=== JSON files ===")
    for rel in ["config.example.json", "projects/tsp/project.json", "projects/mnist_digits/project.json"]:
        path = ROOT / rel
        checks.append(ok(f"JSON parse {rel}", path.exists()))
        if path.exists():
            try:
                load_json(path)
                checks.append(ok(f"JSON valid {rel}", True))
                checks.append(check_json_style(path))
            except Exception as exc:
                checks.append(ok(f"JSON valid {rel}", False, str(exc)))

    print("\n=== secrets ===")
    text_files = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".md", ".py", ".sh", ".yml", ".yaml", ".txt"}]
    suspicious: list[str] = []
    for path in text_files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                suspicious.append(rel)
                break
    checks.append(ok("no obvious admin/ntfy secrets", not suspicious, ", ".join(sorted(set(suspicious)))[:400]))

    print("\n=== runtime artefacts ===")
    runtime_leftovers: list[str] = []
    for root_name in RUNTIME_ROOTS:
        base = ROOT / root_name
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file() and path.name != ".gitkeep":
                    runtime_leftovers.append(path.relative_to(ROOT).as_posix())
    for project in (ROOT / "projects").glob("*"):
        if not project.is_dir():
            continue
        for dirname, allowed in PROJECT_RUNTIME_RULES.items():
            base = project / dirname
            if base.exists():
                for path in base.rglob("*"):
                    if path.is_file() and path.name not in allowed:
                        runtime_leftovers.append(path.relative_to(ROOT).as_posix())
    checks.append(ok("no runtime artefacts", not runtime_leftovers, ", ".join(runtime_leftovers[:8])))
    checks.append(ok("no generated sample ZIPs", not list((ROOT / "projects").glob("*/*sample_submission.zip"))))

    print("\n=== project examples ===")
    for project_id in ["tsp", "mnist_digits"]:
        pdir = ROOT / "projects" / project_id
        checks.append(ok(f"project {project_id}", (pdir / "project.json").exists()))
        checks.append(ok(f"fake roster {project_id}", (pdir / "documents" / "students.xlsx").exists()))
        checks.append(ok(f"statement {project_id}", (pdir / "statement" / "README.md").exists()))
        checks.append(ok(f"sample solution {project_id}", (pdir / "sample_solution").exists()))
    return 0 if all(checks) else 1


def normal_check(argv: list[str]) -> int:
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
        status = "experimental" if profile.get("status") == "experimental" else "stable"
        checks.append(ok(f"language profile {lang}", True, f"{profile.get('docker_image', '')} ({status})"))
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--public-release" in argv:
        argv.remove("--public-release")
        if argv:
            print("--public-release cannot be combined with other check options", file=sys.stderr)
            return 2
        return public_release_check()
    return normal_check(argv)


if __name__ == "__main__":
    raise SystemExit(main())

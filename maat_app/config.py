from __future__ import annotations

from pathlib import Path
from typing import Any

from .profiles import (
    flatten_public_config,
    load_json,
    normalize_language_code,
    unwrap,
    unwrap_tree,
    validate_value_comment_file,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def default_config_language(raw_cfg: dict[str, Any]) -> str:
    return normalize_language_code(unwrap(raw_cfg.get("interface", {}).get("language", {"value": "fr"}), "fr"))


def load_config(lang: str | None = None) -> dict[str, Any]:
    raw_cfg = load_json(CONFIG_PATH)
    validate_config(raw_cfg)
    selected_lang = normalize_language_code(lang) if lang is not None else default_config_language(raw_cfg)
    cfg = flatten_public_config(raw_cfg, selected_lang)
    cfg["root_dir"] = str(ROOT)
    cfg["language"] = selected_lang

    active_project = str(cfg.get("active_project", "projects/tsp"))
    project_dir = resolve_path(active_project)
    project_raw = load_json(project_dir / "project.json")
    validate_value_comment_file(project_raw, str(project_dir / "project.json"))
    project = unwrap_tree(project_raw, selected_lang)

    def pget(section: str, key: str, default: Any = None) -> Any:
        block = project.get(section)
        if isinstance(block, dict) and key in block:
            return block[key]
        return project.get(key, default)

    project_id = str(pget("project", "id", project_dir.name))
    allowed_languages = [str(item) for item in pget("project", "allowed_languages", [])]
    if not allowed_languages:
        allowed_languages = [str(pget("project", "default_language", "cpp"))]
    default_language = str(pget("project", "default_language", allowed_languages[0]))
    if default_language not in allowed_languages:
        default_language = allowed_languages[0]

    language_profiles: dict[str, dict[str, Any]] = {}
    for language_id in allowed_languages:
        language_profiles[language_id] = load_language_profile(language_id, selected_lang)

    cfg.update({
        "active_project_abs": str(project_dir),
        "project_id": project_id,
        "project_title": pget("project", "title", project_id),
        "project_description": pget("project", "description", ""),
        "project": project,
        "allowed_languages": allowed_languages,
        "default_language": default_language,
        "language_profiles": language_profiles,
        "project_metrics": list(pget("scoring", "metrics", [])),
        "primary_metric": str(pget("scoring", "primary_metric", (pget("scoring", "metrics", []) or [{"name": "score"}])[0].get("name", "score"))),
        "output_format": pget("scoring", "output_format", ""),
        "school_name": pget("interface", "school_name", cfg.get("school_name", "")),
        "course_name": pget("interface", "course_name", cfg.get("course_name", "")),
        "student_level": pget("interface", "student_level", cfg.get("student_level", "")),
        "submission_cooldown_seconds": int(pget("submission_limits", "cooldown_seconds", cfg.get("submission_cooldown_seconds", 300))),
        "max_zip_size_mb": int(pget("submission_limits", "max_zip_size_mb", cfg.get("max_zip_size_mb", 20))),
        "max_files_per_zip": int(pget("submission_limits", "max_file_count_per_zip", cfg.get("max_files_per_zip", 100))),
        "max_uncompressed_size_mb": int(pget("submission_limits", "max_uncompressed_size_mb", cfg.get("max_uncompressed_size_mb", 80))),
        "max_output_bytes": int(pget("submission_limits", "max_output_bytes", cfg.get("max_output_bytes", 200000))),
        "session_timer_enabled": bool(pget("teaching_session", "timer_enabled", cfg.get("session_timer_enabled", True))),
        "session_duration_minutes": int(pget("teaching_session", "duration_minutes", cfg.get("session_duration_minutes", 240))),
        "snapshot_interval_minutes": int(pget("teaching_session", "snapshot_interval_minutes", cfg.get("snapshot_interval_minutes", 30))),
    })
    documents_dir = (project_dir / str(pget("directories", "documents_directory", "documents"))).resolve()
    results_dir = (project_dir / str(pget("directories", "results_directory", "results"))).resolve()
    data_dir = project_dir / str(pget("data", "data_directory", "data"))
    cfg["documents_dir_abs"] = str(documents_dir)
    cfg["results_dir_abs"] = str(results_dir)
    cfg["data_dir_abs"] = str(data_dir.resolve())
    cfg["public_instances_glob"] = str(pget("data", "instances_pattern", "instance_*.txt"))
    cfg["private_instances_glob"] = "__none__"
    cfg["support_files"] = [str(item) for item in pget("data", "support_files", [])]

    # Compatibility aliases for existing modules and templates.
    default_profile = language_profiles[default_language]
    cfg["docker_image"] = default_profile.get("docker_image", "maat-cpp-runner:latest")
    cfg["allowed_source_extensions"] = sorted({ext for profile in language_profiles.values() for ext in profile.get("allowed_extensions", [])})
    cfg["ignored_zip_prefixes"] = [".git/", "build/", "cmake-build-debug/", "cmake-build-release/", "Debug/", "Release/", "x64/", ".vs/", ".vscode/", "__pycache__/"]
    cfg["compile_timeout_seconds"] = int(default_profile.get("compile_timeout_seconds", 30))
    cfg["run_timeout_seconds"] = int(default_profile.get("run_timeout_seconds", 180))
    cfg["run_parallel_threads"] = 2
    cfg["compile_parallel_jobs"] = 2
    cfg["executable_name"] = "main"
    cfg["score_regex"] = primary_metric_def(cfg).get("regex", r"score\s*(?:->|:)\s*([-+]?\d+(?:\.\d+)?)")
    cfg["ranking_policy"] = "best_completed_non_canceled_primary_metric_per_student"

    student_roster = Path(str(pget("students", "roster_xlsx_path", "documents/students.xlsx")))
    students_csv = Path(str(pget("students", "generated_students_csv", "documents/students.csv")))
    if not student_roster.is_absolute():
        student_roster = project_dir / student_roster
    if not students_csv.is_absolute():
        students_csv = project_dir / students_csv
    snapshot_dir = Path(str(pget("teaching_session", "snapshot_directory", "results/snapshots")))
    if not snapshot_dir.is_absolute():
        snapshot_dir = project_dir / snapshot_dir
    cfg["student_roster_xlsx"] = str(pget("students", "roster_xlsx_path", "documents/students.xlsx"))
    cfg["students_csv"] = str(pget("students", "generated_students_csv", "documents/students.csv"))
    cfg["student_roster_xlsx_abs"] = str(student_roster.resolve())
    cfg["students_csv_abs"] = str(students_csv.resolve())
    cfg["submissions_dir_abs"] = str(ROOT / "submissions")
    cfg["runs_dir_abs"] = str(ROOT / "runs")
    cfg["logs_dir_abs"] = str(ROOT / "logs")
    cfg["database_path_abs"] = str((documents_dir / "maat.sqlite3").resolve())
    cfg["snapshot_directory_abs"] = str(snapshot_dir.resolve())
    return cfg


def load_language_profile(language_id: str, lang: str | None = None) -> dict[str, Any]:
    path = ROOT / "languages" / language_id / "language.json"
    raw = load_json(path)
    profile = unwrap_tree(raw, lang or "en")
    profile.setdefault("id", language_id)
    profile.setdefault("allowed_extensions", [])
    profile.setdefault("entrypoints", [])
    profile.setdefault("forbidden_patterns", [])
    profile.setdefault("allow_custom_build_file", False)
    profile.setdefault("compile_resources", {})
    profile.setdefault("run_resources", {})
    return profile


def primary_metric_def(cfg: dict[str, Any]) -> dict[str, Any]:
    name = str(cfg.get("primary_metric", "score"))
    for metric in cfg.get("project_metrics", []) or []:
        if str(metric.get("name")) == name:
            return metric
    metrics = cfg.get("project_metrics", []) or []
    return metrics[0] if metrics else {"name": "score", "higher_is_better": True, "aggregation": "sum"}


def validate_config(raw_cfg: dict[str, Any]) -> None:
    if not isinstance(raw_cfg, dict):
        raise ValueError("config.json must contain a JSON object.")
    validate_value_comment_file(raw_cfg, "config.json")


def unwrap_value(value: Any, lang: str | None = None) -> Any:
    return unwrap(value, lang)


def normalize_config(raw_cfg: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    selected = normalize_language_code(lang) if lang else default_config_language(raw_cfg)
    return flatten_public_config(raw_cfg, selected)


def collect_config_comments(raw_cfg: dict[str, Any]) -> dict[str, str]:
    comments: dict[str, str] = {}
    for section, section_value in raw_cfg.items():
        if not isinstance(section_value, dict):
            continue
        for key, value in section_value.items():
            if isinstance(value, dict) and isinstance(value.get("comment"), str):
                comments[f"{section}.{key}"] = value["comment"]
    return comments


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def ensure_runtime_dirs() -> None:
    cfg = load_config()
    for name in ("submissions", "runs", "logs", "translations"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    for key in ("documents_dir_abs", "results_dir_abs", "snapshot_directory_abs"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)

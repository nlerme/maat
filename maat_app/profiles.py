from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LanguageProfile:
    """Declarative language profile loaded from languages/<id>/language.json."""
    id: str
    data: dict[str, Any]

    @property
    def docker_image(self) -> str:
        return str(self.data.get("docker_image", ""))

    @property
    def allowed_extensions(self) -> list[str]:
        return [str(x) for x in self.data.get("allowed_extensions", [])]


@dataclass(frozen=True)
class ProjectProfile:
    """Declarative project profile loaded from projects/<id>/project.json."""
    id: str
    root: Path
    data: dict[str, Any]

    @property
    def metrics(self) -> list[dict[str, Any]]:
        return list(self.data.get("metrics", []))


@dataclass(frozen=True)
class SubmissionPlan:
    """Effective plan used to evaluate one submission."""
    project: ProjectProfile
    language: LanguageProfile
    build_command: str
    run_command: str


def normalize_language_code(lang: str | None) -> str:
    value = str(lang or "fr").lower()
    return "en" if value.startswith("en") else "fr"


def unwrap(value: Any, lang: str | None = None) -> Any:
    if isinstance(value, dict):
        selected = normalize_language_code(lang)
        if "value" in value:
            inner = value["value"]
            if isinstance(inner, dict) and ("fr" in inner or "en" in inner):
                return inner.get(selected, inner.get("fr", inner.get("en")))
            return inner
        if selected in value and ("fr" in value or "en" in value):
            return value.get(selected, value.get("fr", value.get("en")))
    return value


def unwrap_tree(value: Any, lang: str | None = None) -> Any:
    if isinstance(value, dict):
        if "value" in value and "comment" in value:
            return unwrap(value, lang)
        return {key: unwrap_tree(item, lang) for key, item in value.items()}
    if isinstance(value, list):
        return [unwrap_tree(item, lang) for item in value]
    return value


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def flatten_public_config(raw_cfg: dict[str, Any], lang: str) -> dict[str, Any]:
    section_map: dict[tuple[str, str], str] = {
        ("interface", "language"): "language",
        ("interface", "github_url"): "github_url",
        ("interface", "license_url"): "lgpl_v3_url",
        ("interface", "developer_name"): "developer_name",
        ("interface", "developer_mail"): "developer_mail",
        ("server", "listen_host"): "listen_host",
        ("server", "listen_port"): "listen_port",
        ("server", "public_url"): "public_url",
        ("server", "admin_token"): "admin_token",
        ("students", "random_seed"): "random_seed",
        ("project", "active_project"): "active_project",
        ("submission_security", "bind_token_to_first_client"): "bind_token_to_first_client",
        ("submission_security", "client_ip_header"): "client_ip_header",
        ("submission_security", "fingerprint_uses_user_agent"): "fingerprint_uses_user_agent",
        ("queue", "worker_count"): "queue_workers",
        ("parallelism", "automatic_parallel_settings"): "automatic_parallel_settings",
        ("docker", "bind_mode"): "docker_bind_mode",
        ("docker", "staging_root"): "docker_bind_root",
        ("docker", "staging_cleanup_max_age_hours"): "docker_staging_cleanup_max_age_hours",
        ("docker", "container_user"): "docker_container_user",
        ("docker", "container_home"): "docker_container_home",
        ("docker", "network"): "docker_network",
        ("docker", "cap_drop_all"): "docker_cap_drop_all",
        ("docker", "no_new_privileges"): "docker_no_new_privileges",
        ("docker", "read_only_root_filesystem"): "docker_read_only_root_filesystem",
        ("docker", "tmpfs"): "docker_tmpfs",
        ("docker", "input_mount_read_only"): "docker_input_mount_read_only",
        ("docker", "default_cpus"): "docker_cpus",
        ("docker", "default_memory"): "docker_memory",
        ("docker", "default_pids_limit"): "docker_pids_limit",
        ("tunnel", "watch_interval_minutes"): "tunnel_watch_interval_minutes",
        ("tunnel", "watch_url_timeout_seconds"): "tunnel_watch_url_timeout_seconds",
        ("tunnel", "notifications_enabled"): "tunnel_notifications_enabled",
        ("tunnel", "ntfy_server"): "tunnel_ntfy_server",
        ("tunnel", "ntfy_topic"): "tunnel_ntfy_topic",
        ("tunnel", "ntfy_title"): "tunnel_ntfy_title",
    }
    flat: dict[str, Any] = {}
    for section, body in raw_cfg.items():
        if not isinstance(body, dict):
            continue
        for key, entry in body.items():
            mapped = section_map.get((section, key))
            if mapped:
                flat[mapped] = unwrap(entry, lang)
    flat["app_title"] = unwrap(raw_cfg.get("interface", {}).get("app_title", {"value": "MAAT"}), lang)
    flat["app_name"] = flat["app_title"]
    return flat


def validate_value_comment_file(raw: dict[str, Any], path_label: str) -> None:
    errors: list[str] = []
    for section, body in raw.items():
        if str(section).startswith("_"):
            continue
        if isinstance(body, dict) and "value" in body and "comment" in body:
            entries = {section: body}
        elif isinstance(body, dict):
            entries = {f"{section}.{key}": entry for key, entry in body.items() if not str(key).startswith("_")}
        else:
            continue
        for dotted, entry in entries.items():
            if not isinstance(entry, dict) or "value" not in entry or "comment" not in entry:
                # Internal arrays inside project metrics are allowed to be plain JSON.
                if isinstance(entry, dict) and dotted.endswith(".metrics"):
                    continue
                errors.append(f"{dotted}: expected value/comment object")
                continue
            comment = entry.get("comment")
            if not isinstance(comment, str) or not comment.strip():
                errors.append(f"{dotted}: missing English comment")
            elif not comment.isascii():
                errors.append(f"{dotted}: comment must be ASCII English")
            value = entry.get("value")
            if isinstance(value, dict) and ("fr" in value or "en" in value):
                if "fr" not in value or "en" not in value:
                    errors.append(f"{dotted}: localized value must contain fr and en")
    if errors:
        raise ValueError(f"Invalid {path_label}:\n- " + "\n- ".join(errors))

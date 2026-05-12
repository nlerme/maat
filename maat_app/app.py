from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import subprocess
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for

from .config import ensure_runtime_dirs, load_config
from .i18n import LANGUAGES, TRANSLATIONS, normalize_language, translate
from .leaderboard import best_by_group, best_by_instance_group, export_leaderboards
from .queue_worker import EvaluationQueue
from .reports import submission_report_pdf
from .snapshots import maybe_write_leaderboard_snapshot, start_snapshot_worker
from .storage import Storage
from .utils import format_datetime, format_duration_seconds, truncate_text

cfg = load_config()
ensure_runtime_dirs()
storage = Storage(cfg)
eval_queue = EvaluationQueue(cfg, storage)
try:
    storage.sync_database()
except Exception:
    pass
SESSION_STARTED_TS = time.time()
app = Flask(__name__, template_folder=str(Path(cfg["root_dir"]) / "templates"), static_folder=str(Path(cfg["root_dir"]) / "static"))
app.secret_key = hashlib.sha256(("maat-admin-session\n" + str(cfg.get("admin_token", "maat"))).encode("utf-8")).hexdigest()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
app.config["MAX_CONTENT_LENGTH"] = int(cfg.get("max_zip_size_mb", 20)) * 1024 * 1024

STATUS_META_BASE = {
    "queued": {"abbr": "Q", "label_key": "badge_queued", "class": "text-bg-secondary"},
    "running": {"abbr": "RUN", "label_key": "badge_running", "class": "text-bg-primary"},
    "done": {"abbr": "OK", "label_key": "badge_done", "class": "text-bg-success"},
    "canceled": {"abbr_key": "badge_cancel_short", "label_key": "badge_canceled", "class": "text-bg-secondary"},
    "compile_error": {"abbr": "CE", "label_key": "badge_compile_error", "class": "text-bg-danger"},
    "compile_timeout": {"abbr": "CT", "label_key": "badge_compile_timeout", "class": "text-bg-warning"},
    "runtime_error": {"abbr": "RE", "label_key": "badge_runtime_error", "class": "text-bg-danger"},
    "timeout": {"abbr": "TLE", "label_key": "badge_timeout", "class": "text-bg-warning"},
    "invalid_output": {"abbr": "IO", "label_key": "badge_invalid_output", "class": "text-bg-warning"},
    "invalid_archive": {"abbr": "ZIP", "label_key": "badge_invalid_archive", "class": "text-bg-danger"},
    "missing_expected_file": {"abbr": "MISS", "label_key": "badge_missing_expected_file", "class": "text-bg-danger"},
    "internal_error": {"abbr": "IE", "label_key": "badge_internal_error", "class": "text-bg-dark"},
    "failed": {"abbr": "FAIL", "label_key": "badge_failed", "class": "text-bg-danger"},
    "OK": {"abbr": "OK", "label_key": "badge_ok_instance", "class": "text-bg-success"},
    "TIMEOUT": {"abbr": "TLE", "label_key": "badge_timeout", "class": "text-bg-warning"},
    "RUNTIME_ERROR": {"abbr": "RE", "label_key": "badge_runtime_error", "class": "text-bg-danger"},
    "INVALID_OUTPUT": {"abbr": "IO", "label_key": "badge_invalid_output", "class": "text-bg-warning"},
    "INTERNAL_ERROR": {"abbr": "IE", "label_key": "badge_internal_error", "class": "text-bg-dark"},
    "CANCELED": {"abbr_key": "badge_cancel_short", "label_key": "badge_canceled", "class": "text-bg-secondary"},
}

STATUS_LEGEND_KEYS = [
    "queued",
    "running",
    "done",
    "canceled",
    "compile_error",
    "compile_timeout",
    "runtime_error",
    "timeout",
    "invalid_output",
    "invalid_archive",
    "missing_expected_file",
    "internal_error",
    "failed",
]


def groups() -> list[str]:
    return sorted({student.group for student in storage.load_students().values()})


def current_language() -> str:
    requested = request.args.get("lang") or request.cookies.get("maat-language") or cfg.get("language", "fr")
    return normalize_language(requested)


def session_timer_enabled_value() -> bool:
    return bool(cfg.get("session_timer_enabled", True))


def session_total_seconds_value() -> int:
    return max(0, int(cfg.get("session_duration_minutes", 240) * 60))


def session_remaining_seconds_value() -> int:
    if not session_timer_enabled_value():
        return session_total_seconds_value()
    return max(0, int(session_total_seconds_value() - (time.time() - SESSION_STARTED_TS)))


@app.before_request
def before_request() -> None:
    g.lang = current_language()
    eval_queue.start()
    start_snapshot_worker(storage)
    try:
        maybe_write_leaderboard_snapshot(storage)
    except Exception:
        pass


@app.after_request
def after_request(response):
    response.set_cookie("maat-language", g.get("lang", normalize_language(cfg.get("language", "fr"))), max_age=365 * 24 * 3600, samesite="Lax")
    return response


@app.context_processor
def inject_globals():
    lang = g.get("lang", normalize_language(cfg.get("language", "fr")))
    # Runtime decisions use the process-level cfg loaded at server start.
    # Templates receive a localized view so config translations switch
    # immediately when the user changes the UI language.
    display_cfg = load_config(lang)
    return {
        "groups": groups(),
        "status_meta": status_meta(lang),
        "status_legend_keys": STATUS_LEGEND_KEYS,
        "cfg": display_cfg,
        "lang": lang,
        "languages": LANGUAGES,
        "i18n": TRANSLATIONS[lang],
        "t": lambda key, **kwargs: translate(lang, key, **kwargs),
        "session_timer_enabled": session_timer_enabled_value(),
        "session_remaining_seconds": session_remaining_seconds_value(),
        "session_total_seconds": session_total_seconds_value(),
        "submissions_paused": storage.submissions_paused(),
        "admin_authenticated": admin_authenticated(),
        "csrf_token": csrf_token,
        "project": cfg.get("project", {}),
        "project_metrics": cfg.get("project_metrics", []),
        "language_profiles": cfg.get("language_profiles", {}),
        "allowed_languages": cfg.get("allowed_languages", []),
    }


def status_meta(lang: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for key, meta in STATUS_META_BASE.items():
        result[key] = {
            "abbr": translate(lang, str(meta.get("abbr_key"))) if meta.get("abbr_key") else str(meta.get("abbr", key)),
            "label": translate(lang, str(meta.get("label_key", key))),
            "class": str(meta.get("class", "text-bg-secondary")),
        }
    return result


def _admin_token_configured() -> bool:
    return bool(str(cfg.get("admin_token", "") or ""))


def _valid_admin_token(value: str) -> bool:
    expected = str(cfg.get("admin_token", "") or "")
    return bool(expected) and hmac.compare_digest(str(value or ""), expected)


def admin_authenticated() -> bool:
    if not _admin_token_configured():
        return True
    return bool(session.get("maat_admin_authenticated"))


def require_admin() -> None:
    if not admin_authenticated():
        abort(403)


def csrf_token() -> str:
    token = session.get("maat_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["maat_csrf_token"] = token
    return str(token)


def require_csrf() -> None:
    expected = csrf_token()
    provided = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(str(provided), expected):
        abort(403)


def public_submission_ref(status: dict[str, Any]) -> str:
    return str(status.get("public_id") or status.get("submission_id") or "")


def get_status_by_ref(ref: str, allow_internal_id: bool = False) -> dict[str, Any] | None:
    status = storage.get_status_by_public_id(ref)
    if status:
        return status
    if allow_internal_id:
        return storage.get_status(ref)
    return None


def owner_key_from_request() -> str:
    return (
        request.args.get("owner", "")
        or request.form.get("owner_key", "")
        or request.headers.get("X-MAAT-Owner-Key", "")
    )


def can_access_submission(status: dict[str, Any]) -> bool:
    if admin_authenticated():
        return True
    owner_key = owner_key_from_request()
    return bool(owner_key and hmac.compare_digest(str(owner_key), str(status.get("owner_key", ""))))


def require_submission_access(status: dict[str, Any]) -> None:
    if not can_access_submission(status):
        abort(403)


def natural_instance_name_key(name: str) -> list[Any]:
    parts = re.split(r"(\d+)", name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def configured_instance_names() -> list[str]:
    data_dir = Path(cfg["data_dir_abs"])
    if not data_dir.exists():
        return []
    public = sorted((path.name for path in data_dir.glob(str(cfg.get("public_instances_glob", "public_*.txt")))), key=natural_instance_name_key)
    private = sorted((path.name for path in data_dir.glob(str(cfg.get("private_instances_glob", "private_*.txt")))), key=natural_instance_name_key)
    return public + private


def add_aggregate_fields(status: dict[str, Any]) -> None:
    instances = list(status.get("instances") or [])
    ok_rows = [row for row in instances if row.get("status") == "OK"]
    metrics = status.setdefault("metrics", {}) or {}
    for metric in cfg.get("project_metrics", []) or []:
        name = str(metric.get("name", ""))
        if not name or metrics.get(name) is not None:
            continue
        vals = [float((row.get("metrics") or {}).get(name, row.get(name))) for row in ok_rows if (row.get("metrics") or {}).get(name, row.get(name)) is not None]
        if not vals:
            metrics[name] = None
            continue
        agg = str(metric.get("aggregation", "sum"))
        if agg == "mean": metrics[name] = round(sum(vals) / len(vals), 6)
        elif agg == "min": metrics[name] = min(vals)
        elif agg == "max": metrics[name] = max(vals)
        else: metrics[name] = round(sum(vals), 6)
    status["metrics"] = metrics
    primary = str(cfg.get("primary_metric", "score"))
    if status.get("score_total") is None:
        status["score_total"] = metrics.get(primary)


def add_display_fields(status: dict[str, Any]) -> dict[str, Any]:
    result = dict(status)
    add_aggregate_fields(result)
    result["expected_instances"] = configured_instance_names()
    instances = list(result.get("instances") or [])
    passed = int(result.get("valid_instances", 0) or 0)
    if "failed_instances" in result:
        failed = int(result.get("failed_instances", 0) or 0)
    else:
        failed = sum(1 for item in instances if item.get("status") and item.get("status") != "OK")
    result["passed_instances"] = passed
    result["failed_instances"] = failed
    for key in ("submitted_at", "started_at", "finished_at", "canceled_at"):
        if result.get(key):
            result[key] = format_datetime(result.get(key))
    return result


def localize_status(status: dict[str, Any]) -> dict[str, Any]:
    result = add_display_fields(status)
    internal_id = str(result.get("submission_id", ""))
    public_ref = public_submission_ref(result)
    result["internal_submission_id"] = internal_id
    result["submission_id"] = public_ref
    result["public_id"] = public_ref
    for item in result.get("instances", []) or []:
        if isinstance(item, dict):
            for stream_key in ("stdout_url", "stderr_url"):
                url = str(item.get(stream_key, ""))
                if url and internal_id and f"/submission/{internal_id}/" in url:
                    item[stream_key] = url.replace(f"/submission/{internal_id}/", f"/submission/{public_ref}/", 1)
    result.pop("token", None)
    result.pop("owner_key", None)
    result.pop("zip_path", None)
    key = result.get("message_key")
    if key:
        result["message"] = translate(g.lang, str(key), **dict(result.get("message_args") or {}))
    return result


def public_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    localized = localize_status(status)
    return {
        "submission_id": localized.get("submission_id"),
        "group": localized.get("group"),
        "heuristic_name": localized.get("heuristic_name", ""),
        "language": localized.get("language"),
        "status": localized.get("status"),
        "message": localized.get("message"),
        "score_total": localized.get("score_total"),
        "metrics": localized.get("metrics", {}),
        "language": localized.get("language"),
        "project_id": localized.get("project_id"),
        "valid_instances": localized.get("valid_instances"),
        "total_instances": localized.get("total_instances"),
        "expected_instances_count": len(configured_instance_names()),
        "total_runtime_seconds": localized.get("total_runtime_seconds"),
        "mean_nb_words": localized.get("mean_nb_words"),
        "mean_curvature": localized.get("mean_curvature"),
        "passed_instances": localized.get("passed_instances", localized.get("valid_instances", 0)),
        "failed_instances": localized.get("failed_instances", 0),
        "submitted_at": localized.get("submitted_at"),
    }




def admin_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    localized = localize_status(status)
    return {
        "submission_id": localized.get("submission_id"),
        "group": localized.get("group"),
        "animal": localized.get("animal", ""),
        "first_name": localized.get("first_name", ""),
        "last_name": localized.get("last_name", ""),
        "heuristic_name": localized.get("heuristic_name", ""),
        "status": localized.get("status"),
        "message": localized.get("message"),
        "score_total": localized.get("score_total"),
        "metrics": localized.get("metrics", {}),
        "language": localized.get("language"),
        "project_id": localized.get("project_id"),
        "passed_instances": localized.get("passed_instances", localized.get("valid_instances", 0)),
        "failed_instances": localized.get("failed_instances", 0),
        "total_instances": localized.get("total_instances") or len(configured_instance_names()),
        "total_runtime_seconds": localized.get("total_runtime_seconds"),
        "submitted_at": localized.get("submitted_at"),
    }


def client_identity(browser_fingerprint: str = "") -> tuple[str, str]:
    header = str(cfg.get("client_ip_header", "") or "").strip()
    if header:
        ip = request.headers.get(header, request.remote_addr or "")
        ip = ip.split(",", 1)[0].strip()
    else:
        ip = request.remote_addr or ""
    ua = request.headers.get("User-Agent", "")[:200]
    browser_fingerprint = (browser_fingerprint or "")[:500]
    raw = ip if not cfg.get("fingerprint_uses_user_agent", True) else f"{ip}\n{ua}\n{browser_fingerprint}"
    salt = str(cfg.get("admin_token", "maat"))
    fingerprint = hashlib.sha256((salt + "\n" + raw).encode("utf-8", errors="ignore")).hexdigest()
    label = f"{ip} / {ua[:120]}"
    if browser_fingerprint:
        label += f" / fp={browser_fingerprint[:32]}"
    return fingerprint, label


def kill_container(name: str | None) -> None:
    if not name:
        return
    subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def kill_submission_containers(submission_id: str, current_name: str | None = None) -> None:
    import time

    prefix = f"maat_{submission_id}_"
    names = [current_name] if current_name else []
    for _ in range(12):
        for name in names:
            kill_container(name)
        try:
            completed = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name={prefix}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
        except Exception:
            return
        ids = [item.strip() for item in completed.stdout.splitlines() if item.strip()]
        if ids:
            subprocess.run(["docker", "rm", "-f", *ids], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if not ids and not names:
            break
        names = []
        time.sleep(0.2)


def system_metrics() -> dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_percent = round(min(999.0, 100.0 * load1 / max(1, cpu_count)), 1)
    except OSError:
        load1 = load5 = load15 = 0.0
        cpu_percent = None
    mem_total = mem_available = None
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1]) * 1024
        mem_total = values.get("MemTotal")
        mem_available = values.get("MemAvailable")
    except Exception:
        pass
    ram_percent = None
    ram_used_mb = ram_total_mb = None
    if mem_total and mem_available is not None:
        used = mem_total - mem_available
        ram_percent = round(100.0 * used / mem_total, 1)
        ram_used_mb = round(used / (1024 * 1024), 1)
        ram_total_mb = round(mem_total / (1024 * 1024), 1)
    return {
        "cpu_count": cpu_count,
        "load1": round(load1, 2),
        "load5": round(load5, 2),
        "load15": round(load15, 2),
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
        "ram_used_mb": ram_used_mb,
        "ram_total_mb": ram_total_mb,
        "submissions_paused": storage.submissions_paused(),
        "session_timer_enabled": session_timer_enabled_value(),
        "session_remaining_seconds": session_remaining_seconds_value(),
        "session_total_seconds": session_total_seconds_value(),
        "active_project": cfg.get("project_id"),
        "allowed_languages": cfg.get("allowed_languages", []),
    }


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")


@app.route("/submit", methods=["POST"])
def submit():
    token = request.form.get("token", "").strip().upper().replace("-", "")
    heuristic_name = request.form.get("heuristic_name", "").strip()
    uploaded = request.files.get("file")
    requested_language = request.form.get("language", "").strip() or str(cfg.get("default_language", "cpp"))
    if session_timer_enabled_value() and session_remaining_seconds_value() <= 0:
        return render_template("index.html", error=translate(g.lang, "session_finished"), heuristic_name=heuristic_name), 403
    if storage.submissions_paused():
        return render_template("index.html", error=translate(g.lang, "submissions_paused"), heuristic_name=heuristic_name), 403
    if not token:
        return render_template("index.html", error=translate(g.lang, "missing_token"), heuristic_name=heuristic_name), 400
    if not uploaded:
        return render_template("index.html", error=translate(g.lang, "missing_zip"), heuristic_name=heuristic_name), 400
    if not heuristic_name:
        return render_template("index.html", error=translate(g.lang, "missing_heuristic"), heuristic_name=heuristic_name), 400
    if requested_language not in (cfg.get("allowed_languages") or []):
        return render_template("index.html", error=translate(g.lang, "unsupported_language", language=requested_language), heuristic_name=heuristic_name), 400
    heuristic_name = heuristic_name[:80]
    students = storage.load_students()
    student = students.get(token)
    if not student:
        return render_template("index.html", error=translate(g.lang, "unknown_token"), heuristic_name=heuristic_name), 403
    browser_fp = request.form.get("browser_fingerprint", "")
    fingerprint, label = client_identity(browser_fp)
    if not storage.validate_client_binding(token, fingerprint, label):
        return render_template("index.html", error=translate(g.lang, "client_mismatch"), heuristic_name=heuristic_name), 403
    allowed, message_key, remaining, fallback_message = storage.validate_submission_allowed(token)
    if not allowed:
        message = translate(g.lang, message_key) if message_key else fallback_message
        return render_template(
            "index.html",
            error=message,
            remaining=remaining,
            remaining_human=format_duration_seconds(remaining),
            heuristic_name=heuristic_name,
        ), 429
    submission_id = storage.next_submission_id()
    try:
        zip_path = storage.secure_save_zip(uploaded, submission_id, language_id=requested_language)
        status = storage.create_submission(token, student, zip_path, heuristic_name, language_id=requested_language)
    except ValueError as exc:
        return render_template("index.html", error=str(exc), heuristic_name=heuristic_name), 400
    eval_queue.enqueue(status["submission_id"])
    return redirect(url_for("submission", status_ref=public_submission_ref(status), owner=status.get("owner_key", "")))


@app.route("/submission/<status_ref>", methods=["GET"])
def submission(status_ref: str):
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    require_submission_access(status)
    owner = owner_key_from_request()
    owner_param = ("?owner=" + owner) if owner else ""
    return render_template("submission.html", status=localize_status(status), owner_param=owner_param)


@app.route("/submission/<status_ref>/cancel", methods=["POST"])
def cancel_submission(status_ref: str):
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    if not can_access_submission(status):
        abort(403)
    if admin_authenticated() and not owner_key_from_request():
        require_csrf()
    submission_id = str(status.get("submission_id", ""))
    container_name = status.get("current_container_name")
    if status.get("status") == "canceled":
        return jsonify(localize_status(status))
    canceled = storage.cancel_submission(submission_id)
    kill_submission_containers(submission_id, container_name)
    export_leaderboards(storage)
    return jsonify(localize_status(canceled or status))


@app.route("/api/submission/<status_ref>", methods=["GET"])
def api_submission(status_ref: str):
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    require_submission_access(status)
    internal_id = str(status.get("submission_id", ""))
    status = localize_status(status)
    if status.get("status") == "queued":
        status["queue_position"] = eval_queue.position(internal_id)
    return jsonify(status)


@app.route("/api/submissions", methods=["GET"])
def api_submissions():
    token = request.args.get("token", "").strip().upper().replace("-", "")
    rows = []
    if token:
        statuses = [status for status in storage.list_statuses() if str(status.get("token", "")).upper() == token]
        statuses.sort(key=lambda status: float(status.get("submitted_ts", 0.0) or 0.0), reverse=True)
        rows = [public_status_summary(status) for status in statuses[:100]]
    else:
        raw_ids = request.args.get("ids", "")
        ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        for status_ref in ids[:100]:
            status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
            if status:
                rows.append(public_status_summary(status))
    return jsonify({"rows": rows})


@app.route("/api/admin/submissions", methods=["GET"])
def api_admin_submissions():
    require_admin()
    statuses = sorted(storage.list_statuses(), key=lambda s: s.get("submission_id", ""), reverse=True)
    return jsonify({"rows": [admin_status_summary(status) for status in statuses[:500]]})


@app.route("/submission/<status_ref>/compile/<stream>", methods=["GET"])
def compile_output(status_ref: str, stream: str):
    if stream not in {"stdout", "stderr"}:
        abort(404)
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    require_submission_access(status)
    submission_id = str(status.get("submission_id", ""))
    path = Path(cfg["runs_dir_abs"]) / submission_id / f"compile.{stream}.txt"
    if not path.exists():
        abort(404)
    text, truncated = truncate_text(path, int(cfg.get("max_output_bytes", 200000)))
    owner = owner_key_from_request()
    owner_param = ("?owner=" + owner) if owner else ""
    return render_template("output.html", submission_id=public_submission_ref(status), instance_key="compilation", stream=f"compile {stream}", text=text, truncated=truncated, owner_param=owner_param)


@app.route("/submission/<status_ref>/instance/<instance_key>/<stream>", methods=["GET"])
def output(status_ref: str, instance_key: str, stream: str):
    if stream not in {"stdout", "stderr"}:
        abort(404)
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    require_submission_access(status)
    path = storage.output_path(str(status.get("submission_id", "")), instance_key, stream)
    if not path.exists():
        abort(404)
    text, truncated = truncate_text(path, int(cfg.get("max_output_bytes", 200000)))
    owner = owner_key_from_request()
    owner_param = ("?owner=" + owner) if owner else ""
    return render_template("output.html", submission_id=public_submission_ref(status), instance_key=instance_key, stream=stream, text=text, truncated=truncated, owner_param=owner_param)


@app.route("/leaderboard/<group>", methods=["GET"])
def leaderboard(group: str):
    is_admin = admin_authenticated()
    return render_template("leaderboard.html", group=group, is_admin=is_admin)


@app.route("/api/leaderboard/<group>", methods=["GET"])
def api_leaderboard(group: str):
    is_admin = admin_authenticated()

    def public_global_row(row: dict[str, Any]) -> dict[str, Any]:
        add_aggregate_fields(row)
        item = {
            "rank": row.get("rank"),
            "animal": row.get("animal", ""),
            "heuristic_name": row.get("heuristic_name", ""),
            "submission_id": public_submission_ref(row),
            "score_total": row.get("score_total"),
            "metrics": row.get("metrics", {}),
            "language": row.get("language"),
            "valid_instances": row.get("valid_instances"),
            "total_instances": row.get("total_instances"),
            "total_runtime_seconds": row.get("total_runtime_seconds"),
            "passed_instances": row.get("valid_instances", 0),
            "failed_instances": row.get("failed_instances", 0),
            "submitted_at": format_datetime(row.get("submitted_at")),
        }
        if is_admin:
            item["last_name"] = row.get("last_name")
            item["first_name"] = row.get("first_name")
            item["internal_submission_id"] = row.get("submission_id")
        return item

    def public_instance_row(row: dict[str, Any]) -> dict[str, Any]:
        item = {
            "instance": row.get("instance", ""),
            "rank": row.get("rank"),
            "animal": row.get("animal", ""),
            "heuristic_name": row.get("heuristic_name", ""),
            "submission_id": public_submission_ref(row),
            "score": row.get("score"),
            "metrics": row.get("metrics", {}),
            "runtime_seconds": row.get("runtime_seconds"),
            "submitted_at": format_datetime(row.get("submitted_at")),
        }
        if is_admin:
            item["last_name"] = row.get("last_name")
            item["first_name"] = row.get("first_name")
            item["internal_submission_id"] = row.get("submission_id")
        return item

    global_rows = [public_global_row(row) for row in best_by_group(storage, group).get(group, [])]
    instance_rows = [public_instance_row(row) for row in best_by_instance_group(storage, group).get(group, [])]
    return jsonify({
        "group": group,
        "rows": global_rows,
        "global_rows": global_rows,
        "instance_rows": instance_rows,
        "instance_names": configured_instance_names(),
        "is_admin": is_admin,
        "metric_defs": cfg.get("project_metrics", []),
    })


@app.route("/submission/<status_ref>/report.pdf", methods=["GET"])
def submission_report(status_ref: str):
    status = get_status_by_ref(status_ref, allow_internal_id=admin_authenticated())
    if not status:
        abort(404)
    require_submission_access(status)
    pdf = submission_report_pdf(add_display_fields(status), cfg.get("project_metrics", []))
    public_ref = public_submission_ref(status)
    headers = {"Content-Disposition": f"attachment; filename=maat_submission_{public_ref}.pdf"}
    return Response(pdf, mimetype="application/pdf", headers=headers)


@app.route("/api/personal_stats/<group>", methods=["GET"])
def api_personal_stats(group: str):
    token = request.args.get("token", "").strip().upper().replace("-", "")
    if not token:
        return jsonify({"available": False})
    statuses = [s for s in storage.list_statuses() if s.get("token") == token and s.get("group") == group and s.get("status") == "done" and not s.get("cancel_requested") and not s.get("canceled_at") and s.get("score_total") is not None]
    statuses.sort(key=lambda s: float(s.get("submitted_ts", 0.0) or 0.0))
    if not statuses:
        return jsonify({"available": False})
    for s in statuses:
        add_aggregate_fields(s)
    latest = statuses[-1]
    global_rows = best_by_group(storage, group).get(group, [])
    ranked_best = next((row for row in global_rows if row.get("token") == token), statuses[-1])
    rank = next((row.get("rank") for row in global_rows if row.get("token") == token), None)
    first_score = float(global_rows[0].get("score_total", 0.0)) if global_rows else None
    best_score = float(ranked_best.get("score_total", 0.0) or 0.0)
    prev_score = float(statuses[-2].get("score_total", 0.0) or 0.0) if len(statuses) >= 2 else None
    history = [float(s.get("score_total", 0.0) or 0.0) for s in statuses[-8:]]
    return jsonify({
        "available": True,
        "attempts": len(statuses),
        "history": history,
        "latest_score": float(latest.get("score_total", 0.0) or 0.0),
        "best_score": best_score,
        "rank": rank,
        "delta_first": None if first_score is None else first_score - best_score,
        "delta_previous": None if prev_score is None else float(latest.get("score_total", 0.0) or 0.0) - prev_score,
    })


def error_category(status: dict[str, Any]) -> str:
    state = str(status.get("status", ""))
    if state == "compile_error":
        return "compile_error_category"
    if state == "compile_timeout":
        return "compile_timeout_category"
    if state == "canceled":
        return "canceled_category"
    if state == "invalid_archive":
        return "invalid_archive_category"
    if state == "missing_expected_file":
        return "missing_expected_file_category"
    if state == "internal_error":
        return "internal_error_category"
    inst = status.get("instances", []) or []
    if any(row.get("status") == "TIMEOUT" for row in inst):
        return "timeout_category"
    if any(row.get("status") == "RUNTIME_ERROR" for row in inst):
        return "runtime_error_category"
    if any(row.get("status") == "INVALID_OUTPUT" for row in inst):
        return "invalid_output_category"
    return state or "unknown"


def admin_summary_data() -> dict[str, Any]:
    statuses = storage.list_statuses()
    students = storage.load_students()
    tokens_with_submissions = {s.get("token") for s in statuses if s.get("token")}
    by_group = Counter(str(s.get("group", "")) for s in statuses)
    compile_errors = [s for s in statuses if s.get("status") in {"compile_error", "compile_timeout"}]
    compile_errors.sort(key=lambda s: str(s.get("submitted_at", "")), reverse=True)
    error_counter = Counter()
    for s in statuses:
        failed_rows = [row for row in (s.get("instances", []) or []) if row.get("status") and row.get("status") not in {"OK", "CANCELED", "queued", "running"}]
        if failed_rows:
            for row in failed_rows:
                msg = str(row.get("message") or row.get("status") or s.get("message", ""))[:120]
                error_counter[(error_category(s), msg)] += 1
        elif s.get("status") != "done" or int(s.get("failed_instances", 0) or 0) > 0:
            error_counter[(error_category(s), str(s.get("message", ""))[:120])] += 1
    canceled = [s for s in statuses if s.get("status") == "canceled" or s.get("canceled_at")]
    timeouts = [s for s in statuses if s.get("status") in {"compile_timeout", "timeout"} or any(row.get("status") == "TIMEOUT" for row in (s.get("instances", []) or []))]
    best_global = []
    for rows in best_by_group(storage).values():
        best_global.extend(rows)
    # best_by_group already applies the project-specific ranking direction.
    best_instance = []
    for rows in best_by_instance_group(storage).values():
        best_instance.extend(rows)
    best_instance.sort(key=lambda r: (str(r.get("instance", "")), int(r.get("rank", 999))))
    return {
        "submissions_by_group": sorted(by_group.items()),
        "students_without_submission": [student for token, student in students.items() if token not in tokens_with_submissions],
        "latest_compile_errors": [localize_status(s) for s in compile_errors[:10]],
        "top_errors": [(cat, msg, count) for (cat, msg), count in error_counter.most_common(10)],
        "canceled": [localize_status(s) for s in sorted(canceled, key=lambda s: str(s.get("submitted_at", "")), reverse=True)[:20]],
        "timeouts": [localize_status(s) for s in sorted(timeouts, key=lambda s: str(s.get("submitted_at", "")), reverse=True)[:20]],
        "best_global": [localize_status(s) for s in best_global[:20]],
        "best_instance": [localize_status(s) for s in best_instance[:30]],
        "system": system_metrics(),
    }


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        require_csrf()
        token = request.form.get("admin_token", "")
        if _valid_admin_token(token):
            session["maat_admin_authenticated"] = True
            csrf_token()
            next_url = request.form.get("next", "") or url_for("admin")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("admin")
            return redirect(next_url)
        return render_template("admin_login.html", error=translate(g.lang, "admin_login_failed"), next=request.form.get("next", "")), 403
    if admin_authenticated():
        return redirect(url_for("admin"))
    return render_template("admin_login.html", next=request.args.get("next", ""))


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    require_csrf()
    session.pop("maat_admin_authenticated", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/summary", methods=["GET", "POST"])
def admin_summary():
    if not admin_authenticated():
        return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))
    notice = ""
    if request.method == "POST":
        require_csrf()
        token = request.form.get("token", "").strip().upper().replace("-", "")
        action = request.form.get("action", "")
        if token and action == "unlock":
            storage.unlock_cooldown(token)
            notice = translate(g.lang, "admin_action_done")
        elif token and action == "purge":
            for status in storage.list_statuses():
                if status.get("token") == token:
                    kill_submission_containers(str(status.get("submission_id", "")), status.get("current_container_name"))
            storage.purge_student_submissions(token)
            export_leaderboards(storage)
            notice = translate(g.lang, "admin_action_done")
        elif action == "purge_all":
            for status in storage.list_statuses():
                kill_submission_containers(str(status.get("submission_id", "")), status.get("current_container_name"))
            storage.purge_all_submissions()
            export_leaderboards(storage)
            notice = translate(g.lang, "admin_action_done")
        elif action == "pause_submissions":
            storage.set_submissions_paused(True)
            notice = translate(g.lang, "submissions_pause_done")
        elif action == "resume_submissions":
            storage.set_submissions_paused(False)
            notice = translate(g.lang, "submissions_resume_done")
        else:
            notice = translate(g.lang, "admin_action_failed")
    return render_template("admin_summary.html", data=admin_summary_data(), notice=notice)


@app.route("/admin", methods=["GET"])
def admin():
    if not admin_authenticated():
        return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))
    statuses = sorted((localize_status(s) for s in storage.list_statuses()), key=lambda s: s.get("internal_submission_id", ""), reverse=True)
    return render_template("admin.html", statuses=statuses, system=system_metrics())


@app.route("/admin/submissions/toggle", methods=["POST"])
def admin_toggle_submissions():
    require_admin()
    require_csrf()
    action = request.form.get("action", "")
    storage.set_submissions_paused(action == "pause_submissions")
    target = request.form.get("target", "admin")
    endpoint = "admin_summary" if target == "summary" else "admin"
    return redirect(url_for(endpoint))


@app.route("/api/admin/system", methods=["GET"])
def api_admin_system():
    require_admin()
    return jsonify(system_metrics())


@app.route("/admin/export/leaderboard.csv", methods=["GET"])
def admin_export_leaderboard_csv():
    require_admin()
    export_leaderboards(storage)
    output = io.StringIO()
    metric_names = [str(m.get("name")) for m in cfg.get("project_metrics", []) or []]
    fieldnames = ["rank", "group", "symbol", "last_name", "first_name", "heuristic_name", "language", "submission_id", "internal_submission_id", *metric_names, "valid_instances", "failed_instances", "total_instances", "total_runtime_seconds", "submitted_at"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for group_name, rows in sorted(best_by_group(storage).items()):
        for row in rows:
            csv_row = {key_name: row.get(key_name, "") for key_name in fieldnames}
            csv_row["symbol"] = row.get("animal", "")
            csv_row["internal_submission_id"] = row.get("submission_id", "")
            csv_row["submission_id"] = public_submission_ref(row)
            for name in metric_names:
                csv_row[name] = (row.get("metrics") or {}).get(name, row.get(name, ""))
            writer.writerow(csv_row)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=maat_classement_final.csv"},
    )


@app.route("/admin/export/session.zip", methods=["GET"])
def admin_export_session_zip():
    require_admin()
    export_leaderboards(storage)
    payload = io.BytesIO()
    root = Path(cfg["root_dir"])
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        def add_file(path: Path, arcname: str) -> None:
            if path.exists() and path.is_file():
                zf.write(path, arcname)

        add_file(root / "config.json", "config.json")
        active_project = Path(cfg.get("active_project_abs", ""))
        if active_project.exists():
            for path in sorted(p for p in active_project.rglob("*") if p.is_file()):
                add_file(path, path.relative_to(root).as_posix())
        for lang_id in cfg.get("allowed_languages", []):
            lang_dir = root / "languages" / str(lang_id)
            if lang_dir.exists():
                for path in sorted(p for p in lang_dir.rglob("*") if p.is_file()):
                    add_file(path, path.relative_to(root).as_posix())
        for folder in (Path(cfg.get("results_dir_abs")), Path(cfg.get("documents_dir_abs")), root / "logs", root / "submissions"):
            if folder.exists():
                for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                    add_file(path, path.relative_to(root).as_posix())
        runs_root = root / "runs"
        if runs_root.exists():
            useful_names = {"status.json", "results.csv", "compile.stdout.txt", "compile.stderr.txt"}
            for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
                for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
                    rel = path.relative_to(run_dir).as_posix()
                    if path.name in useful_names or rel.startswith("instances/"):
                        add_file(path, path.relative_to(root).as_posix())
        for status in sorted(storage.list_statuses(), key=lambda row: str(row.get("submission_id", ""))):
            public_ref = public_submission_ref(status)
            if not public_ref:
                continue
            zf.writestr(f"reports/maat_submission_{public_ref}.pdf", submission_report_pdf(add_display_fields(status), cfg.get("project_metrics", [])))
    payload.seek(0)
    return Response(
        payload.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=maat_session_export.zip"},
    )


@app.route("/download/<status_ref>", methods=["GET"])
def download(status_ref: str):
    require_admin()
    status = get_status_by_ref(status_ref, allow_internal_id=True)
    if not status:
        abort(404)
    return send_file(status["zip_path"], as_attachment=True)


def main() -> None:
    app.run(host=str(cfg.get("listen_host", "0.0.0.0")), port=int(cfg.get("listen_port", 8000)), threaded=True)


if __name__ == "__main__":
    main()

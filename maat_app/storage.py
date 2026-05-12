from __future__ import annotations

import csv
import secrets
import threading
import time
import zipfile
import shutil
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .db import MaatDatabase
from .models import Student
from .utils import atomic_write_json, now_iso, read_json, safe_name


class Storage:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.root = Path(cfg["root_dir"])
        self.students_csv = Path(cfg["students_csv_abs"])
        self.submissions_dir = Path(cfg["submissions_dir_abs"])
        self.runs_dir = Path(cfg["runs_dir_abs"])
        self.results_dir = Path(cfg["results_dir_abs"])
        self.documents_dir = Path(cfg["documents_dir_abs"])
        self.counter_file = self.documents_dir / "counter.txt"
        self.client_bindings_file = self.documents_dir / "token_clients.json"
        self.counter_lock = threading.Lock()
        self.binding_lock = threading.Lock()
        self.unlocks_file = self.documents_dir / "cooldown_unlocks.json"
        self.pause_file = self.documents_dir / "submissions_paused.json"
        self.db = MaatDatabase(self.cfg.get("database_path_abs", self.documents_dir / "maat.sqlite3"))

    def load_students(self) -> dict[str, Student]:
        if not self.students_csv.exists():
            return {}
        students: dict[str, Student] = {}
        with self.students_csv.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                token = row.get("token", "").strip()
                if not token:
                    continue
                students[token] = Student(
                    group=row.get("group", "").strip(),
                    last_name=row.get("last_name", "").strip(),
                    first_name=row.get("first_name", "").strip(),
                    token=token,
                    animal=row.get("animal", "").strip(),
                    animal_entity=row.get("animal_entity", "").strip(),
                )
        seen_animals: dict[str, str] = {}
        duplicates: list[str] = []
        for token, student in students.items():
            if not student.animal:
                continue
            if student.animal in seen_animals:
                duplicates.append(f"{student.animal} ({seen_animals[student.animal]}, {token})")
            else:
                seen_animals[student.animal] = token
        if duplicates:
            raise ValueError("Duplicate animal emoji in students.csv: " + ", ".join(duplicates))
        return students

    def next_submission_id(self) -> str:
        with self.counter_lock:
            self.counter_file.parent.mkdir(parents=True, exist_ok=True)
            current = 0
            if self.counter_file.exists():
                text = self.counter_file.read_text(encoding="utf-8").strip()
                current = int(text) if text else 0
            current += 1
            self.counter_file.write_text(str(current), encoding="utf-8")
            return f"{current:06d}"

    def list_statuses(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.runs_dir.exists():
            return result
        for path in sorted(self.runs_dir.glob("*/status.json")):
            data = read_json(path, {})
            if data:
                submission_id = str(data.get("submission_id") or path.parent.name)
                data = self.ensure_public_id(submission_id, data)
                result.append(data)
        return result

    def get_status(self, submission_id: str) -> dict[str, Any] | None:
        if not submission_id.isdigit():
            return None
        path = self.runs_dir / submission_id / "status.json"
        if not path.exists():
            return None
        data = read_json(path, {})
        return self.ensure_public_id(submission_id, data) if data else None

    def get_status_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        public_id = str(public_id or "").strip()
        if not public_id:
            return None
        for status in self.list_statuses():
            if str(status.get("public_id", "")) == public_id:
                return status
        return None

    def ensure_public_id(self, submission_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("public_id"):
            return data
        data["public_id"] = self.new_public_id()
        atomic_write_json(self.runs_dir / submission_id / "status.json", data)
        try:
            self.db.sync_submission(data)
        except Exception:
            pass
        return data

    def new_public_id(self) -> str:
        existing: set[str] = set()
        if self.runs_dir.exists():
            for path in self.runs_dir.glob("*/status.json"):
                data = read_json(path, {})
                if data.get("public_id"):
                    existing.add(str(data.get("public_id")))
        while True:
            value = secrets.token_urlsafe(16)
            if value not in existing:
                return value

    def save_status(self, submission_id: str, data: dict[str, Any]) -> None:
        atomic_write_json(self.runs_dir / submission_id / "status.json", data)
        try:
            self.db.sync_submission(data)
        except Exception:
            pass

    def validate_submission_allowed(self, token: str) -> tuple[bool, str, int, str]:
        cooldown = int(self.cfg.get("submission_cooldown_seconds", 300))
        now_ts = time.time()
        active = {"queued", "running"}
        latest_ts: float | None = None
        for status in self.list_statuses():
            if status.get("token") != token:
                continue
            if status.get("status") in active:
                return False, "already_active", 0, "Un dépôt est déjà en attente ou en cours pour ce token."
            submitted_ts = float(status.get("submitted_ts", 0.0) or 0.0)
            if latest_ts is None or submitted_ts > latest_ts:
                latest_ts = submitted_ts
        if latest_ts is not None:
            unlocks = read_json(self.unlocks_file, {})
            unlock_ts = float(unlocks.get(token, 0.0) or 0.0)
            if unlock_ts < latest_ts:
                remaining = cooldown - int(now_ts - latest_ts)
                if remaining > 0:
                    return False, "cooldown", remaining, "Vous devez attendre avant de déposer à nouveau."
        return True, "", 0, ""

    def validate_client_binding(self, token: str, fingerprint: str, label: str) -> bool:
        if not bool(self.cfg.get("bind_token_to_first_client", False)):
            return True
        with self.binding_lock:
            bindings = read_json(self.client_bindings_file, {})
            existing = bindings.get(token)
            if existing is None:
                bindings[token] = {"fingerprint": fingerprint, "label": label, "bound_at": now_iso()}
                atomic_write_json(self.client_bindings_file, bindings)
                return True
            return str(existing.get("fingerprint", "")) == fingerprint

    def secure_save_zip(self, uploaded: FileStorage, submission_id: str, language_id: str | None = None) -> Path:
        filename = secure_filename(uploaded.filename or "submission.zip")
        if not filename.lower().endswith(".zip"):
            raise ValueError("Le fichier déposé doit être une archive .zip.")
        path = self.submissions_dir / f"{submission_id}_{filename}"
        uploaded.save(path)
        max_bytes = int(self.cfg.get("max_zip_size_mb", 20)) * 1024 * 1024
        if path.stat().st_size > max_bytes:
            path.unlink(missing_ok=True)
            raise ValueError(f"Archive trop volumineuse : limite {self.cfg.get('max_zip_size_mb')} Mo.")
        try:
            self.validate_zip_content(path, language_id=language_id)
        except zipfile.BadZipFile:
            path.unlink(missing_ok=True)
            raise ValueError("Archive ZIP invalide ou corrompue.")
        except ValueError:
            path.unlink(missing_ok=True)
            raise
        return path

    def validate_zip_content(self, zip_path: Path, language_id: str | None = None) -> None:
        max_files = int(self.cfg.get("max_files_per_zip", 100))
        max_uncompressed = int(self.cfg.get("max_uncompressed_size_mb", 80)) * 1024 * 1024
        profiles = self.cfg.get("language_profiles", {}) or {}
        selected_profiles = [profiles.get(language_id)] if language_id and profiles.get(language_id) else list(profiles.values())
        allowed_ext = {str(ext).lower() for profile in selected_profiles if isinstance(profile, dict) for ext in profile.get("allowed_extensions", [])}
        allow_makefile = any(bool(profile.get("allow_custom_build_file", False)) for profile in selected_profiles if isinstance(profile, dict))
        ignored_prefixes = tuple(str(prefix).lower() for prefix in self.cfg.get("ignored_zip_prefixes", []))
        total = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > max_files:
                raise ValueError(f"Archive refusée : plus de {max_files} fichiers.")
            for info in infos:
                name = info.filename.replace("\\", "/")
                lower_name = name.lower().lstrip("/")
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Archive refusée : chemin non sûr détecté.")
                mode = (info.external_attr >> 16) & 0o170000
                permissions = (info.external_attr >> 16) & 0o777
                if mode == 0o120000:
                    raise ValueError("Archive refusée : liens symboliques interdits.")
                if any(lower_name.startswith(prefix) for prefix in ignored_prefixes):
                    continue
                total += info.file_size
                if total > max_uncompressed:
                    raise ValueError(f"Archive refusée : contenu décompressé supérieur à {self.cfg.get('max_uncompressed_size_mb')} Mo.")
                if not info.is_dir():
                    path_name = Path(name).name.lower()
                    ext = Path(name).suffix.lower()
                    is_allowed_text_candidate = (allow_makefile and path_name == "makefile") or ext in allowed_ext
                    # A source file may accidentally carry the executable bit,
                    # especially when ZIP archives are produced on Linux/macOS.
                    # Do not reject allowed C/C++ sources for that metadata alone;
                    # real binaries are still rejected below by content inspection.
                    if permissions & 0o111 and not is_allowed_text_candidate:
                        raise ValueError(f"Archive refusée : fichier exécutable interdit : {name}.")
                    if not is_allowed_text_candidate:
                        raise ValueError(f"Extension non autorisée dans l'archive : {ext or '(aucune)'}")
                    with zf.open(info, "r") as handle:
                        sample = handle.read(min(info.file_size, 1024 * 1024))
                    if b"\0" in sample:
                        raise ValueError(f"Archive refusée : fichier binaire interdit : {name}.")

    def create_submission(self, token: str, student: Student, zip_path: Path, heuristic_name: str = "", language_id: str | None = None) -> dict[str, Any]:
        submission_id = zip_path.name.split("_", 1)[0]
        run_dir = self.runs_dir / submission_id
        run_dir.mkdir(parents=True, exist_ok=True)
        status = {
            "submission_id": submission_id,
            "public_id": self.new_public_id(),
            "owner_key": secrets.token_urlsafe(24),
            "group": student.group,
            "last_name": student.last_name,
            "first_name": student.first_name,
            "token": token,
            "animal": student.animal,
            "animal_entity": student.animal_entity,
            "heuristic_name": heuristic_name,
            "language": language_id or self.cfg.get("default_language", "cpp"),
            "project_id": self.cfg.get("project_id"),
            "project_title": self.cfg.get("project_title"),
            "zip_path": str(zip_path),
            "status": "queued",
            "submitted_at": now_iso(),
            "submitted_ts": time.time(),
            "started_at": None,
            "finished_at": None,
            "canceled_at": None,
            "score_total": None,
            "valid_instances": 0,
            "failed_instances": 0,
            "total_instances": 0,
            "total_runtime_seconds": 0.0,
            "compile_runtime_seconds": None,
            "current_instance": None,
            "current_container_name": None,
            "cancel_requested": False,
            "message": "Dépôt en file d'attente.",
            "message_key": "queued_msg",
            "message_args": {},
            "instances": [],
        }
        self.save_status(submission_id, status)
        return status

    def cancel_submission(self, submission_id: str) -> dict[str, Any] | None:
        status = self.get_status(submission_id)
        if not status:
            return None
        if status.get("status") == "canceled":
            return status
        status["cancel_requested"] = True
        status["status"] = "canceled"
        status["canceled_at"] = now_iso()
        status["finished_at"] = status.get("finished_at") or status["canceled_at"]
        for item in status.get("instances", []) or []:
            if item.get("status") in {"queued", "running"}:
                item["status"] = "CANCELED"
        status["current_container_name"] = None
        status["message"] = "Dépôt annulé/retiré."
        status["message_key"] = "canceled_msg"
        status["message_args"] = {}
        self.save_status(submission_id, status)
        return status

    def is_canceled(self, submission_id: str) -> bool:
        status = self.get_status(submission_id)
        return bool(status and (status.get("status") == "canceled" or status.get("cancel_requested")))

    def unlock_cooldown(self, token: str) -> None:
        unlocks = read_json(self.unlocks_file, {})
        unlocks[token] = time.time()
        atomic_write_json(self.unlocks_file, unlocks)

    def submissions_paused(self) -> bool:
        state = read_json(self.pause_file, {})
        return bool(state.get("paused", False))

    def set_submissions_paused(self, paused: bool) -> None:
        atomic_write_json(self.pause_file, {"paused": bool(paused), "updated_at": now_iso()})

    def purge_student_submissions(self, token: str) -> int:
        removed = 0
        for status in list(self.list_statuses()):
            if status.get("token") != token:
                continue
            removed += self._purge_status(status)
        return removed

    def purge_all_submissions(self) -> int:
        removed = 0
        for status in list(self.list_statuses()):
            removed += self._purge_status(status)
        return removed

    def _purge_status(self, status: dict[str, Any]) -> int:
        submission_id = str(status.get("submission_id", ""))
        if not submission_id:
            return 0
        zip_path = status.get("zip_path")
        if zip_path:
            try:
                Path(zip_path).unlink(missing_ok=True)
            except Exception:
                pass
        shutil.rmtree(self.runs_dir / submission_id, ignore_errors=True)
        try:
            self.db.delete_submission(submission_id)
        except Exception:
            pass
        return 1

    def sync_database(self) -> None:
        self.db.sync_all(self.list_statuses())

    def output_path(self, submission_id: str, instance_key: str, stream: str) -> Path:
        return self.runs_dir / submission_id / "instances" / safe_name(instance_key) / f"{stream}.txt"

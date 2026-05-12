from __future__ import annotations

import csv
import re
import shlex
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from .docker_runner import DockerRunner
from .storage import Storage
from .utils import now_iso, safe_name, truncate_text


class InvalidArchiveError(RuntimeError):
    """Raised when the submitted ZIP cannot be safely evaluated."""


class MissingExpectedFileError(InvalidArchiveError):
    """Raised when the expected project entry point is missing."""


class ForbiddenPatternError(InvalidArchiveError):
    """Raised when a forbidden source pattern is detected."""


class Evaluator:
    def __init__(self, cfg: dict[str, Any], storage: Storage):
        self.cfg = cfg
        self.storage = storage
        self.runner = DockerRunner(cfg)

    def evaluate(self, submission_id: str) -> None:
        status = self.storage.get_status(submission_id)
        if not status or self.storage.is_canceled(submission_id):
            return
        try:
            status.update({"status": "running", "started_at": now_iso(), "message": "Evaluation running.", "message_key": "running_msg", "message_args": {}})
            self.storage.save_status(submission_id, status)
            run_dir = Path(self.cfg["runs_dir_abs"]) / submission_id
            zip_path = Path(status["zip_path"])
            language_id = str(status.get("language") or self.cfg.get("default_language", "cpp"))
            profile = self.language_profile(language_id)
            project_dir = self.prepare_project(run_dir, zip_path, language_id)
            data_dir = self.prepare_project_data(run_dir)
            self.check_forbidden_patterns(project_dir, profile)
            if self.storage.is_canceled(submission_id):
                return
            compile_ok = self.compile_project(run_dir, project_dir, status, profile)
            if not compile_ok or self.storage.is_canceled(submission_id):
                return
            self.run_instances(run_dir, project_dir, status, profile, data_dir)
        except MissingExpectedFileError as exc:
            self.finish_with_error(submission_id, status, "missing_expected_file", str(exc), "missing_expected_file_msg")
        except InvalidArchiveError as exc:
            self.finish_with_error(submission_id, status, "invalid_archive", str(exc), "invalid_archive_msg", {"error": str(exc)})
        except Exception as exc:
            status = self.storage.get_status(submission_id) or status
            if status.get("status") == "canceled":
                self.refresh_submission_metrics(status)
                self.storage.save_status(submission_id, status)
                return
            self.finish_with_error(submission_id, status, "internal_error", f"Internal error: {exc}", "internal_error_msg", {"error": str(exc)})

    def finish_with_error(self, submission_id: str, status: dict[str, Any], state: str, message: str, key: str, args: dict[str, Any] | None = None) -> None:
        latest = self.storage.get_status(submission_id) or status
        latest.update({"status": state, "finished_at": now_iso(), "message": message, "message_key": key, "message_args": args or {}, "current_container_name": None})
        self.storage.save_status(submission_id, latest)

    def language_profile(self, language_id: str) -> dict[str, Any]:
        profiles = self.cfg.get("language_profiles", {}) or {}
        profile = profiles.get(language_id)
        if not isinstance(profile, dict):
            raise InvalidArchiveError(f"Language is not allowed for this project: {language_id}.")
        return profile

    def prepare_project(self, run_dir: Path, zip_path: Path, language_id: str) -> Path:
        extract_dir = run_dir / "extract"
        project_dir = run_dir / "project"
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(project_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.storage.validate_zip_content(zip_path, language_id=language_id)
        except zipfile.BadZipFile as exc:
            raise InvalidArchiveError("Invalid or corrupted ZIP archive.") from exc
        except ValueError as exc:
            raise InvalidArchiveError(str(exc)) from exc
        self.safe_extract(zip_path, extract_dir)
        source_root = self.find_project_root(extract_dir, self.language_profile(language_id))
        shutil.copytree(source_root, project_dir, dirs_exist_ok=True)
        return project_dir

    def prepare_project_data(self, run_dir: Path) -> Path:
        """Copy the active project data into the run directory.

        Docker bind mounts are resolved by the Docker daemon. Directly mounting
        projects/<project>/data can fail with Docker return code 125 when the
        bundle lives on a path that is visible to Python but not to the daemon
        (NAS, mounted volumes, some WSL/Docker Desktop setups). Keeping a
        per-run data copy under run_dir lets the existing staging mechanism map
        both the submitted project and the input data through the same
        Docker-visible directory. The data directory is mounted read-only during
        execution.
        """
        source = Path(self.cfg["data_dir_abs"]).resolve()
        if not source.exists() or not source.is_dir():
            raise InvalidArchiveError(f"Data directory not found: {source}")
        target = run_dir / "data"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        return target

    def safe_extract(self, zip_path: Path, extract_dir: Path) -> None:
        ignored_prefixes = tuple(str(prefix).lower() for prefix in self.cfg.get("ignored_zip_prefixes", []))
        try:
            zf_context = zipfile.ZipFile(zip_path, "r")
        except zipfile.BadZipFile as exc:
            raise InvalidArchiveError("Invalid or corrupted ZIP archive.") from exc
        with zf_context as zf:
            root = extract_dir.resolve()
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                lower_name = name.lower().lstrip("/")
                if name.startswith("/") or ".." in Path(name).parts:
                    raise InvalidArchiveError("Unsafe path in archive.")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise InvalidArchiveError("Archive rejected: symbolic links are not allowed.")
                if any(lower_name.startswith(prefix) for prefix in ignored_prefixes):
                    continue
                target = (extract_dir / name).resolve()
                if root != target and root not in target.parents:
                    raise InvalidArchiveError("Unsafe path in archive.")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    def find_project_root(self, extract_dir: Path, profile: dict[str, Any]) -> Path:
        candidates: list[Path] = []
        for entry in profile.get("entrypoints", []) or []:
            for path in extract_dir.rglob(str(entry)):
                if path.is_file():
                    candidates.append(path.parent if "/" not in str(entry) else path.parents[len(Path(str(entry)).parts) - 1])
        if not candidates:
            expected = ", ".join(str(x) for x in profile.get("entrypoints", [])) or "entry point"
            raise MissingExpectedFileError(f"Missing expected file: no entry point found ({expected}).")
        candidates.sort(key=lambda p: len(p.parts))
        return candidates[0]

    def check_forbidden_patterns(self, project_dir: Path, profile: dict[str, Any]) -> None:
        forbidden = [str(name).strip() for name in profile.get("forbidden_patterns", []) if str(name).strip()]
        if not forbidden:
            return
        allowed_suffixes = {str(ext).lower() for ext in profile.get("allowed_extensions", [])}
        if profile.get("allow_custom_build_file", False):
            allowed_names = {"makefile"}
        else:
            allowed_names = set()
        patterns = [(name, self._forbidden_pattern(name)) for name in sorted(set(forbidden), key=len, reverse=True)]
        for path in project_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed_suffixes and path.name.lower() not in allowed_names:
                continue
            data = path.read_bytes()
            if b"\0" in data:
                rel = path.relative_to(project_dir).as_posix()
                raise ForbiddenPatternError(f"Submission rejected: forbidden binary file detected: {rel}.")
            text = data.decode("utf-8", errors="replace")
            for name, pattern in patterns:
                if pattern.search(text):
                    rel = path.relative_to(project_dir).as_posix()
                    raise ForbiddenPatternError(f"Submission rejected: forbidden pattern detected: {name} in {rel}.")

    @staticmethod
    def _forbidden_pattern(name: str) -> re.Pattern[str]:
        escaped = re.escape(name)
        if "." in name or "::" in name or name.startswith("_"):
            return re.compile(r"(?<![A-Za-z0-9_:.])" + escaped + r"\b")
        return re.compile(r"(?<![A-Za-z0-9_])" + escaped + r"\b")

    def compile_project(self, run_dir: Path, project_dir: Path, status: dict[str, Any], profile: dict[str, Any]) -> bool:
        submission_id = status["submission_id"]
        command = str(profile.get("build_command", "")).strip()
        if not command:
            status.update({"compile_runtime_seconds": 0.0, "message": "No compilation required.", "message_key": "compile_ok_msg", "message_args": {}})
            self.storage.save_status(submission_id, status)
            return True
        container_name = self.container_name(submission_id, "build")
        status.update({"current_container_name": container_name})
        self.storage.save_status(submission_id, status)
        t0 = time.perf_counter()
        returncode, timed_out = self.runner.run(
            run_dir=run_dir,
            workdir="/judging/project",
            command=command,
            timeout_seconds=int(profile.get("compile_timeout_seconds", self.cfg.get("compile_timeout_seconds", 30))),
            stdout_path=run_dir / "compile.stdout.txt",
            stderr_path=run_dir / "compile.stderr.txt",
            profile="compile",
            language_profile=profile,
            container_name=container_name,
            env_vars={"MAKEFLAGS": f"-j{int(self.cfg.get('compile_parallel_jobs', 1))}"},
            cancel_check=lambda: self.storage.is_canceled(submission_id),
        )
        elapsed = round(time.perf_counter() - t0, 3)
        latest = self.storage.get_status(submission_id) or status
        if latest.get("status") == "canceled":
            return False
        status = latest
        status.update({"compile_runtime_seconds": elapsed, "current_container_name": None})
        if timed_out:
            status.update({"status": "compile_timeout", "finished_at": now_iso(), "message": "Compilation time limit exceeded.", "message_key": "compile_timeout_msg", "message_args": {}})
            self.storage.save_status(submission_id, status)
            return False
        if returncode != 0:
            message_key = "compile_error_msg"
            message = "Compilation error."
            if returncode in {137, 143}:
                message_key = "compile_resource_error_msg"
                message = "Compilation error: Docker memory/resource limit probably reached."
            status.update({"status": "compile_error", "finished_at": now_iso(), "message": message, "message_key": message_key, "message_args": {}})
            self.storage.save_status(submission_id, status)
            return False
        status.update({"message": "Compilation succeeded.", "message_key": "compile_ok_msg", "message_args": {}})
        self.storage.save_status(submission_id, status)
        return True

    def run_instances(self, run_dir: Path, project_dir: Path, status: dict[str, Any], profile: dict[str, Any], data_dir: Path) -> None:
        submission_id = status["submission_id"]
        instances = self.list_instances(data_dir)
        status["total_instances"] = len(instances)
        status["instances"] = [self.placeholder_result(submission_id, instance_path, "queued") for instance_path in instances]
        status["total_runtime_seconds"] = 0.0
        status["failed_instances"] = 0
        status["valid_instances"] = 0
        status["score_total"] = None
        status["metrics"] = {}
        self.storage.save_status(submission_id, status)
        for index, instance_path in enumerate(instances, start=1):
            if self.storage.is_canceled(submission_id):
                latest = self.storage.get_status(submission_id) or status
                self.refresh_submission_metrics(latest)
                self.storage.save_status(submission_id, latest)
                return
            instance_key = instance_path.name
            status = self.storage.get_status(submission_id) or status
            self.replace_instance_result(status, index - 1, self.placeholder_result(submission_id, instance_path, "running"))
            status["current_instance"] = instance_key
            status["message"] = f"Instance {index}/{len(instances)} : {instance_key}"
            status["message_key"] = "instance_msg"
            status["message_args"] = {"index": index, "total": len(instances), "instance": instance_key}
            self.storage.save_status(submission_id, status)
            result = self.run_one_instance(run_dir, project_dir, submission_id, instance_path, profile, data_dir)
            latest = self.storage.get_status(submission_id) or status
            status = latest
            self.replace_instance_result(status, index - 1, result)
            self.refresh_submission_metrics(status)
            self.storage.save_status(submission_id, status)
        if self.storage.is_canceled(submission_id):
            latest = self.storage.get_status(submission_id) or status
            self.refresh_submission_metrics(latest)
            self.storage.save_status(submission_id, latest)
            return
        status["status"] = "done"
        status["finished_at"] = now_iso()
        status["current_instance"] = None
        status["current_container_name"] = None
        status["message"] = "Evaluation finished."
        status["message_key"] = "finished_msg"
        status["message_args"] = {}
        self.refresh_submission_metrics(status)
        self.storage.save_status(submission_id, status)
        self.write_results_csv(run_dir, status)

    def placeholder_result(self, submission_id: str, instance_path: Path, state: str) -> dict[str, Any]:
        instance_safe = safe_name(instance_path.stem)
        return {"instance": instance_path.name, "status": state, "metrics": {}, "score": None, "returncode": None, "runtime_seconds": None, "stdout_url": f"/submission/{submission_id}/instance/{instance_safe}/stdout", "stderr_url": f"/submission/{submission_id}/instance/{instance_safe}/stderr", "stdout_truncated": False}

    def run_one_instance(self, run_dir: Path, project_dir: Path, submission_id: str, instance_path: Path, profile: dict[str, Any], data_dir: Path) -> dict[str, Any]:
        instance_safe = safe_name(instance_path.stem)
        out_dir = run_dir / "instances" / instance_safe
        out_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = out_dir / "stdout.txt"
        stderr_path = out_dir / "stderr.txt"
        quoted_instance = shlex.quote(f"/judging/data/{instance_path.name}")
        command = str(profile.get("run_command", "")).replace("{instance_file}", quoted_instance).replace("{project_dir}", "/judging/project").replace("{data_dir}", "/judging/data")
        container_name = self.container_name(submission_id, f"run_{instance_safe}")
        latest = self.storage.get_status(submission_id) or {}
        latest["current_container_name"] = container_name
        self.storage.save_status(submission_id, latest)
        t0 = time.perf_counter()
        returncode, timed_out = self.runner.run(
            run_dir=run_dir,
            workdir="/judging/project",
            command=command,
            timeout_seconds=int(profile.get("run_timeout_seconds", self.cfg.get("run_timeout_seconds", 180))),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            profile="run",
            language_profile=profile,
            container_name=container_name,
            env_vars={"OMP_NUM_THREADS": str(self.cfg.get("run_parallel_threads", 1))},
            cancel_check=lambda: self.storage.is_canceled(submission_id),
            extra_readonly_mounts=[(data_dir, "/judging/data")],
        )
        elapsed = round(time.perf_counter() - t0, 3)
        result = self.placeholder_result(submission_id, instance_path, "OK")
        result.update({"runtime_seconds": elapsed, "returncode": returncode, "output_ready": True})
        if self.storage.is_canceled(submission_id):
            result.update({"status": "CANCELED", "message": "Canceled."})
            return result
        if timed_out or returncode == 124:
            result.update({"status": "TIMEOUT", "message": "Time limit exceeded."})
            return result
        if returncode != 0:
            result.update({"status": "RUNTIME_ERROR", "message": f"Non-zero return code {returncode}."})
            return result
        stdout_text, truncated = truncate_text(stdout_path, int(self.cfg.get("max_output_bytes", 200000)))
        result["stdout_truncated"] = truncated
        parsed = self.parse_metrics(stdout_text)
        if parsed is None:
            result.update({"status": "INVALID_OUTPUT", "message": "Invalid stdout format."})
            return result
        result["metrics"] = parsed
        primary = self.primary_metric_name()
        result["score"] = parsed.get(primary)
        for k, v in parsed.items():
            result[k] = v
        return result

    def parse_metrics(self, text: str) -> dict[str, float] | None:
        values: dict[str, float] = {}
        for metric in self.cfg.get("project_metrics", []) or []:
            name = str(metric.get("name", ""))
            regex = str(metric.get("regex", ""))
            if not name or not regex:
                continue
            m = re.search(regex, text, re.IGNORECASE | re.MULTILINE)
            if not m:
                return None
            try:
                raw = m.group(1)
                values[name] = int(raw) if metric.get("type") == "int" else float(raw)
            except Exception:
                return None
        return values

    def list_instances(self, data_dir: Path | None = None) -> list[Path]:
        data_root = data_dir or Path(self.cfg["data_dir_abs"])
        pattern = str(self.cfg.get("public_instances_glob", "instance_*"))
        return sorted(data_root.glob(pattern), key=lambda p: self.natural_key(p.name))

    def refresh_submission_metrics(self, status: dict[str, Any]) -> None:
        rows = status.get("instances", []) or []
        ok_rows = [row for row in rows if row.get("status") == "OK"]
        status["valid_instances"] = len(ok_rows)
        status["failed_instances"] = sum(1 for row in rows if row.get("status") and row.get("status") not in {"OK", "queued", "running", "CANCELED"})
        status["total_instances"] = len(rows) or status.get("total_instances", 0)
        status["total_runtime_seconds"] = round(sum(float(row.get("runtime_seconds") or 0.0) for row in rows), 3)
        aggregates: dict[str, float] = {}
        for metric in self.cfg.get("project_metrics", []) or []:
            name = str(metric.get("name", ""))
            vals = [float((row.get("metrics") or {}).get(name, row.get(name))) for row in ok_rows if (row.get("metrics") or {}).get(name, row.get(name)) is not None]
            if not vals:
                aggregates[name] = None  # type: ignore[assignment]
                continue
            agg = str(metric.get("aggregation", "sum"))
            if agg == "mean":
                aggregates[name] = round(sum(vals) / len(vals), 6)
            elif agg == "min":
                aggregates[name] = min(vals)
            elif agg == "max":
                aggregates[name] = max(vals)
            else:
                aggregates[name] = round(sum(vals), 6)
        status["metrics"] = aggregates
        primary = self.primary_metric_name()
        status["score_total"] = aggregates.get(primary)

    def write_results_csv(self, run_dir: Path, status: dict[str, Any]) -> None:
        rows = status.get("instances", []) or []
        path = run_dir / "results.csv"
        metric_names = [str(m.get("name")) for m in self.cfg.get("project_metrics", []) or []]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["instance", "status", *metric_names, "runtime_seconds", "returncode"])
            writer.writeheader()
            for row in rows:
                out = {"instance": row.get("instance"), "status": row.get("status"), "runtime_seconds": row.get("runtime_seconds"), "returncode": row.get("returncode")}
                for name in metric_names:
                    out[name] = (row.get("metrics") or {}).get(name, row.get(name))
                writer.writerow(out)

    def replace_instance_result(self, status: dict[str, Any], index: int, result: dict[str, Any]) -> None:
        instances = status.setdefault("instances", [])
        while len(instances) <= index:
            instances.append({})
        instances[index] = result

    def primary_metric_name(self) -> str:
        return str(self.cfg.get("primary_metric") or (self.cfg.get("project_metrics") or [{"name": "score"}])[0].get("name", "score"))

    @staticmethod
    def natural_key(value: str) -> list[Any]:
        parts = re.split(r"(\d+)", value.lower())
        return [int(part) if part.isdigit() else part for part in parts]

    @staticmethod
    def container_name(submission_id: str, phase: str) -> str:
        clean = safe_name(phase)[:48]
        return f"maat_{submission_id}_{clean}"

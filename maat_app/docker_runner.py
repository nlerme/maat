from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class DockerRunner:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.docker_base_cmd = self._detect_docker_base_cmd()

    def _detect_docker_base_cmd(self) -> list[str]:
        if shutil.which("docker") and subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0:
            return ["docker"]
        if shutil.which("sudo") and shutil.which("docker") and subprocess.run(["sudo", "-n", "docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0:
            return ["sudo", "-n", "docker"]
        return ["docker"]

    def _docker_cmd(self, *args: str) -> list[str]:
        return [*self.docker_base_cmd, *args]

    def run(
        self,
        run_dir: Path,
        workdir: str,
        command: str,
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
        profile: str = "run",
        container_name: str | None = None,
        env_vars: dict[str, str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        extra_readonly_mounts: list[tuple[Path, str]] | None = None,
        language_profile: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        """Run one command in Docker.

        A submission directory may be located on a NAS path such as /media/...
        Docker bind mounts are resolved by the Docker daemon, not by this Python
        process. A path readable from the shell can still be unusable by Docker.
        To avoid this class of failures, MAAT stages each run into a local
        Docker-visible directory, runs Docker there, then copies generated files
        back to the original run directory.
        """
        run_dir = run_dir.resolve()
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        if cancel_check and cancel_check():
            return 130, False
        bind_dir, staged = self._prepare_bind_dir(run_dir)
        self._ensure_container_write_access(bind_dir)
        container_name = container_name or f"maat_{uuid.uuid4().hex[:12]}"
        subprocess.run(self._docker_cmd("rm", "-f", container_name), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        docker_cmd = [
            *self.docker_base_cmd,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            str(self.cfg.get("docker_network", "none")),
            "--cpus",
            str(self._resource("cpus", profile, language_profile)),
            "--memory",
            str(self._resource("memory", profile, language_profile)),
            "--memory-swap",
            str(self._resource("memory", profile, language_profile)),
            "--pids-limit",
            str(self._resource("pids_limit", profile, language_profile)),
        ]
        if bool(self.cfg.get("docker_cap_drop_all", True)):
            docker_cmd.append("--cap-drop=ALL")
        if bool(self.cfg.get("docker_no_new_privileges", True)):
            docker_cmd.append("--security-opt=no-new-privileges")
        if bool(self.cfg.get("docker_read_only_root_filesystem", True)):
            docker_cmd.append("--read-only")
        for item in self._tmpfs_mounts():
            target = str(item.get("target", "")).strip()
            options = str(item.get("options", "")).strip()
            if target:
                docker_cmd.extend(["--tmpfs", f"{target}:{options}" if options else target])
        docker_cmd.extend(["--user", self._container_user(), "-e", f"HOME={self.cfg.get('docker_container_home', '/tmp')}"])
        for key, value in (env_vars or {}).items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        docker_cmd.extend(["-v", f"{bind_dir}:/judging"])
        for host_path, target in extra_readonly_mounts or []:
            ro_source = self._map_mount_source(Path(host_path).resolve(), run_dir, bind_dir, staged)
            docker_cmd.extend(["-v", f"{ro_source}:{target}:ro"])
        docker_cmd.extend([
            "-w",
            workdir,
            str((language_profile or {}).get("docker_image") or self.cfg.get("docker_image", "maat-cpp-runner:latest")),
            "bash",
            "-lc",
            command,
        ])

        timed_out = False
        canceled = False
        returncode = 1
        try:
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen(docker_cmd, stdout=out, stderr=err)
                deadline = time.monotonic() + timeout_seconds + 5
                while True:
                    rc = process.poll()
                    if rc is not None:
                        returncode = rc
                        break
                    if cancel_check and cancel_check():
                        canceled = True
                        returncode = 130
                        subprocess.run(self._docker_cmd("rm", "-f", container_name), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        try:
                            returncode = process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        break
                    if time.monotonic() > deadline:
                        timed_out = True
                        returncode = 124
                        subprocess.run(self._docker_cmd("rm", "-f", container_name), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        break
                    time.sleep(0.25)
        finally:
            if canceled:
                for _ in range(8):
                    subprocess.run(self._docker_cmd("rm", "-f", container_name), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    time.sleep(0.15)
            if staged:
                # Never copy the staged status.json back: it is a stale snapshot
                # taken before the Docker run. Copying it back can overwrite a
                # freshly canceled submission with an old running state.
                self._copy_tree_contents(bind_dir, run_dir, skip_root_names={"status.json"})
                shutil.rmtree(bind_dir, ignore_errors=True)
        return returncode, timed_out

    def _prepare_bind_dir(self, run_dir: Path) -> tuple[Path, bool]:
        mode = str(self.cfg.get("docker_bind_mode", "staging")).lower()
        if mode == "direct":
            return run_dir, False

        root = Path(str(self.cfg.get("docker_bind_root", "/tmp/maat-docker-runs"))).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self._cleanup_staging_root(root)
        bind_dir = root / f"{run_dir.name}-{uuid.uuid4().hex[:12]}"
        if bind_dir.exists():
            shutil.rmtree(bind_dir)
        bind_dir.mkdir(parents=True)
        self._copy_tree_contents(run_dir, bind_dir)
        return bind_dir.resolve(), True

    def _map_mount_source(self, host_path: Path, run_dir: Path, bind_dir: Path, staged: bool) -> Path:
        if not staged:
            return host_path
        try:
            rel = host_path.relative_to(run_dir)
        except ValueError:
            return host_path
        return (bind_dir / rel).resolve()

    def _copy_tree_contents(self, src: Path, dst: Path, skip_root_names: set[str] | None = None) -> None:
        skip_root_names = skip_root_names or set()
        dst.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            return
        for item in src.iterdir():
            if item.name in skip_root_names:
                continue
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    def _cleanup_staging_root(self, root: Path) -> None:
        max_age_hours = float(self.cfg.get("docker_staging_cleanup_max_age_hours", 24) or 0)
        if max_age_hours <= 0:
            return
        cutoff = time.time() - max_age_hours * 3600.0
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass

    def _ensure_container_write_access(self, bind_dir: Path) -> None:
        if not self._container_user():
            return
        for root, dirs, files in os.walk(bind_dir):
            try:
                os.chmod(root, 0o777)
            except OSError:
                pass
            for dirname in dirs:
                try:
                    os.chmod(Path(root) / dirname, 0o777)
                except OSError:
                    pass
            for filename in files:
                path = Path(root) / filename
                try:
                    mode = path.stat().st_mode
                    # Preserve executable files created during compilation.
                    # In staging mode MAAT copies the run directory before each
                    # Docker command; blindly chmod-ing every file to 0666 makes
                    # compiled binaries non-executable and turns every instance
                    # into a runtime error. Source files remain writable, while
                    # already-executable files such as ./main keep execute bits.
                    os.chmod(path, 0o777 if (mode & 0o111) else 0o666)
                except OSError:
                    pass

    def _container_user(self) -> str:
        user = str(self.cfg.get("docker_container_user", "65532:65532") or "65532:65532").strip()
        if not user or user == "host":
            user = "65532:65532"
        uid_part = user.split(":", 1)[0].strip().lower()
        if uid_part in {"0", "root"}:
            return "65532:65532"
        return user

    def _tmpfs_mounts(self) -> list[dict[str, Any]]:
        value = self.cfg.get("docker_tmpfs", [])
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _resource(self, name: str, profile: str, language_profile: dict[str, Any] | None = None) -> Any:
        defaults = {"cpus": "1.0", "memory": "512m", "pids_limit": 128}
        if language_profile:
            res_key = "compile_resources" if profile == "compile" else "run_resources"
            resources = language_profile.get(res_key, {}) if isinstance(language_profile.get(res_key, {}), dict) else {}
            if name in resources:
                return resources[name]
        return self.cfg.get(f"docker_{name}", defaults[name])

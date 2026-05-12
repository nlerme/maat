#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/logs/server.pid"
LOG_FILE="$ROOT_DIR/logs/server.log"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENDOR_DIR="$ROOT_DIR/vendor"
CACHE_DIR="$ROOT_DIR/.install-cache"

cd "$ROOT_DIR"

mode="${1:-}"
if [[ -z "$mode" ]]; then
  echo "Usage: $0 {install|check|doctor|uninstall|start|stop|restart|logs|list-projects|set-project|new-project|build-runners|build-samples|init-config}" >&2
  exit 2
fi

ensure_dirs() {
  mkdir -p submissions runs logs "$CACHE_DIR"
  find projects -mindepth 1 -maxdepth 1 -type d -exec mkdir -p {}/documents {}/results \; 2>/dev/null || true
}

warn_if_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    echo "WARNING: MAAT is running as root." >&2
    echo "WARNING: Use a regular user with Docker access whenever possible." >&2
    echo "WARNING: Docker containers still use the non-root user configured in config.json." >&2
  fi
}

python_with_vendor() {
  PYTHONPATH="$ROOT_DIR:$VENDOR_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" "$@"
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Error: administrator privileges are required to install missing dependency: $*" >&2
    exit 1
  fi
}

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return $?
  fi
  # The Flask worker runs non-interactively. Therefore MAAT may only rely on
  # sudo when Docker can be used without a password prompt. Interactive sudo
  # during install would build the image but later evaluations would still fail.
  if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    sudo -n docker "$@"
    return $?
  fi
  echo "Error: Docker is installed but this user cannot access the Docker daemon non-interactively." >&2
  echo "Fix Docker access, then rerun ./manage-maat.sh install:" >&2
  echo "  sudo systemctl enable --now docker" >&2
  echo "  sudo groupadd -f docker" >&2
  echo '  sudo usermod -aG docker "$USER"' >&2
  echo "Then log out/log in again, or run: newgrp docker" >&2
  echo "Check with: docker info" >&2
  return 1
}

build_docker_image() {
  local lang_dir profile image context cache_file ctx_hash lang_id
  shopt -s nullglob
  for lang_dir in "$ROOT_DIR"/languages/*; do
    [[ -d "$lang_dir" && -f "$lang_dir/language.json" ]] || continue
    lang_id="$(basename "$lang_dir")"
    profile="$lang_dir/language.json"
    image="$(PYTHONPATH="$VENDOR_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" - "$profile" <<'PY'
import json, sys
p=sys.argv[1]
print(json.load(open(p, encoding='utf-8')).get('docker_image',''))
PY
)"
    [[ -n "$image" ]] || continue
    context="$ROOT_DIR/docker/${lang_id}-runner"
    cache_file="$CACHE_DIR/docker_${lang_id}_context.sha256"
    if [[ ! -d "$context" || ! -f "$context/Dockerfile" ]]; then
      echo "Warning: Docker build context missing for language '$lang_id': $context" >&2
      continue
    fi
    if [[ "${MAAT_FORCE_DOCKER_BUILD:-0}" != "1" ]] && docker_cmd image inspect "$image" >/dev/null 2>&1; then
      if [[ -f "$cache_file" ]]; then
        ctx_hash="$(context_hash "$context")"
        if [[ "$(cat "$cache_file")" == "$ctx_hash" ]]; then
          echo "Docker image $image already built for current $lang_id context; skipping."
          continue
        fi
      else
        echo "Docker image $image already exists; skipping Docker build."
        continue
      fi
    fi
    if ! docker_cmd buildx version >/dev/null 2>&1; then
      echo "Error: Docker Buildx is required to build MAAT runner images." >&2
      exit 1
    fi
    ctx_hash="$(context_hash "$context")"
    echo "Building Docker image $image from $context"
    docker_cmd buildx build --load -t "$image" "$context"
    printf '%s
' "$ctx_hash" > "$cache_file"
  done
  shopt -u nullglob
}

install_system_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update
    run_as_root apt-get install -y "$@"
  elif command -v dnf >/dev/null 2>&1; then
    run_as_root dnf install -y "$@"
  elif command -v yum >/dev/null 2>&1; then
    run_as_root yum install -y "$@"
  elif command -v pacman >/dev/null 2>&1; then
    run_as_root pacman -Sy --needed --noconfirm "$@"
  elif command -v brew >/dev/null 2>&1; then
    brew install "$@"
  else
    echo "Error: unable to install missing packages automatically: $*" >&2
    echo "Install them manually, then rerun ./manage-maat.sh install." >&2
    exit 1
  fi
}

check_python() {
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    if [[ "$PYTHON_BIN" != "python3" ]] && command -v python3 >/dev/null 2>&1; then
      PYTHON_BIN="python3"
    else
      echo "Python 3 not found. Attempting automatic installation..."
      install_system_packages python3 python3-pip python3-venv
      PYTHON_BIN="$(command -v python3)"
    fi
  fi
  if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    echo "Error: Python >= 3.9 is required." >&2
    exit 1
  fi
}

ensure_pip() {
  check_python
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  echo "pip not found for $PYTHON_BIN. Attempting automatic installation..."
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || install_system_packages python3-pip
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "Error: pip is still unavailable for $PYTHON_BIN." >&2
    exit 1
  fi
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found. Attempting automatic installation..."
    if command -v apt-get >/dev/null 2>&1; then
      install_system_packages docker.io
    elif command -v dnf >/dev/null 2>&1; then
      install_system_packages docker
    elif command -v yum >/dev/null 2>&1; then
      install_system_packages docker
    elif command -v pacman >/dev/null 2>&1; then
      install_system_packages docker
    elif command -v brew >/dev/null 2>&1; then
      brew install --cask docker || brew install docker
    else
      echo "Error: Docker is required and could not be installed automatically." >&2
      exit 1
    fi
    if command -v systemctl >/dev/null 2>&1; then
      run_as_root systemctl enable --now docker >/dev/null 2>&1 || true
    fi
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is still unavailable after installation attempt." >&2
    exit 1
  fi
  docker_cmd version >/dev/null
}

check_core_tools() {
  local archive_missing=()
  command -v unzip >/dev/null 2>&1 || archive_missing+=("unzip")
  command -v zip >/dev/null 2>&1 || archive_missing+=("zip")
  if [[ ${#archive_missing[@]} -gt 0 ]]; then
    echo "Installing missing archive tools: ${archive_missing[*]}"
    install_system_packages "${archive_missing[@]}"
  fi
  for cmd in find head grep tail nohup; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: required core system command not found: $cmd" >&2
      echo "Install coreutils/findutils/grep for your distribution, then rerun ./manage-maat.sh install." >&2
      exit 1
    fi
  done
}

requirements_hash() {
  "$PYTHON_BIN" - <<'PY_REQ_HASH'
from hashlib import sha256
from pathlib import Path
print(sha256(Path("requirements.txt").read_bytes()).hexdigest())
PY_REQ_HASH
}

context_hash() {
  local context_dir="$1"
  "$PYTHON_BIN" - "$context_dir" <<'PY_CONTEXT_HASH'
from hashlib import sha256
from pathlib import Path
import sys

root = Path(sys.argv[1])
h = sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    rel = path.relative_to(root).as_posix()
    h.update(rel.encode("utf-8") + b"\0")
    h.update(path.read_bytes())
    h.update(b"\0")
print(h.hexdigest())
PY_CONTEXT_HASH
}

install_python_deps() {
  check_core_tools
  ensure_pip
  mkdir -p "$CACHE_DIR"

  local req_hash cache_file
  req_hash="$(requirements_hash)"
  cache_file="$CACHE_DIR/requirements.sha256"

  if [[ -d "$VENDOR_DIR" && -f "$cache_file" && "$(cat "$cache_file")" == "$req_hash" ]]; then
    echo "Python dependencies already installed for current requirements.txt; skipping pip install."
    return 0
  fi

  rm -rf "$VENDOR_DIR"
  mkdir -p "$VENDOR_DIR"
  "$PYTHON_BIN" -m pip install --upgrade --target "$VENDOR_DIR" -r requirements.txt
  printf '%s\n' "$req_hash" > "$cache_file"
}

automatic_parallel_settings_enabled() {
  check_python
  PYTHONNOUSERSITE=1 "$PYTHON_BIN" -S - <<'PY_AUTO_FLAG'
import json
from pathlib import Path

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
value = cfg.get("parallelism", {}).get("automatic_parallel_settings", True)
if isinstance(value, dict):
    value = value.get("value", value.get("value_fr", value.get("value_en", True)))
if isinstance(value, str):
    enabled = value.strip().lower() in {"1", "true", "yes", "on", "y", "oui"}
else:
    enabled = bool(value)
raise SystemExit(0 if enabled else 1)
PY_AUTO_FLAG
}

autotune_parallelism() {
  check_python
  if automatic_parallel_settings_enabled; then
    echo "Auto-tuning MAAT parallelism settings from /proc/cpuinfo..."
    PYTHONNOUSERSITE=1 PYTHONPATH="$ROOT_DIR:$VENDOR_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" -S scripts/autotune_parallelism.py config.json
  else
    echo "Automatic parallelism disabled in config.json; keeping manual settings."
  fi
}

cfg_value() {
  local expr="$1"
  python_with_vendor - <<PY
from maat_app.config import load_config
cfg = load_config()
print($expr)
PY
}

students_csv_current() {
  local output="$1"
  [[ -f "$output" ]] || return 1
  python_with_vendor - "$output" <<'PY_STUDENTS_CURRENT'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    if "animal_entity" not in (reader.fieldnames or []):
        raise SystemExit(1)
    for row in reader:
        if len((row.get("token") or "").strip()) != 16:
            raise SystemExit(1)
raise SystemExit(0)
PY_STUDENTS_CURRENT
}

extract_students() {
  local xlsx output seed example
  xlsx="$(cfg_value 'cfg["student_roster_xlsx_abs"]')"
  output="$(cfg_value 'cfg["students_csv_abs"]')"
  seed="$(cfg_value 'cfg.get("random_seed", 20262026)')"
  example="$ROOT_DIR/examples/students_example.csv"
  if [[ -f "$xlsx" ]]; then
    python_with_vendor scripts/extract_students_from_xlsx.py "$xlsx" "$output" "$seed"
    echo "Students extracted/refreshed to $output"
  elif [[ -f "$output" ]]; then
    echo "No roster XLSX found; keeping existing students CSV: $output"
  elif [[ -f "$example" ]]; then
    mkdir -p "$(dirname "$output")"
    cp "$example" "$output"
    echo "No roster XLSX found; copied demo students CSV to $output"
  else
    echo "Warning: no roster XLSX and no students CSV found. Create $output before a real session." >&2
  fi
}

generate_students_pdf() {
  python_with_vendor scripts/generate_students_pdf.py
}

print_students_table() {
  check_python
  if [[ ! -d "$VENDOR_DIR" ]]; then
    return 0
  fi
  python_with_vendor - <<'PY_STUDENTS'
import csv
from pathlib import Path
from maat_app.config import load_config

cfg = load_config()
path = Path(cfg["students_csv_abs"])
print("")
print("=== MAAT - étudiants et tokens ===")
print(f"Fichier étudiants : {path}")
if not path.exists():
    print("Aucun fichier étudiants trouvé.")
else:
    with path.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("Aucun étudiant trouvé.")
    else:
        print(f"{'Groupe':<8} {'Nom':<24} {'Prénom':<20} {'Token':<18} Symbole")
        print("-" * 86)
        for r in rows:
            group = r.get('group', '')
            last = r.get('last_name', '')
            first = r.get('first_name', '')
            token = r.get('token', '')
            animal = r.get('animal', '') or r.get('animal_entity', '')
            print(f"{group:<8} {last:<24} {first:<20} {token:<18} {animal}")
print("===============================")
print("")
PY_STUDENTS
}

stop_maat_docker_containers() {
  if command -v docker >/dev/null 2>&1; then
    local ids_by_name ids
    ids_by_name="$(docker_cmd ps -aq --filter 'name=^/maat_' 2>/dev/null || true)"
    ids="$(printf '%s
' "$ids_by_name" | awk 'NF && !seen[$0]++')"
    if [[ -n "$ids" ]]; then
      echo "Stopping/removing MAAT Docker containers..."
      docker_cmd rm -f $ids >/dev/null 2>&1 || true
    fi
  fi
}

stop_tunnel_if_present() {
  if [[ -x "$ROOT_DIR/manage-tunnel.sh" ]]; then
    "$ROOT_DIR/manage-tunnel.sh" stop >/dev/null 2>&1 || true
  fi
}

kill_residual_maat_processes() {
  # Defensive cleanup: if a server or a tunnel watcher was started from this
  # bundle but its PID file is stale/missing, it can recreate logs/documents
  # after uninstall. Kill only MAAT-owned processes whose command line,
  # environment or working directory identifies this bundle.
  local pid cmd env cwd matched pids=() self="$$" parent="${PPID:-}"

  for proc in /proc/[0-9]*; do
    [[ -d "$proc" ]] || continue
    pid="${proc##*/}"
    [[ "$pid" == "$self" || -n "$parent" && "$pid" == "$parent" ]] && continue

    cmd="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null || true)"
    [[ -n "$cmd" ]] || continue

    matched=0
    case "$cmd" in
      *"maat_app.app"*|*"manage-tunnel.sh"*|*"cloudflared tunnel"*)
        env="$(tr '\0' '\n' < "$proc/environ" 2>/dev/null || true)"
        cwd="$(readlink -f "$proc/cwd" 2>/dev/null || true)"
        if [[ "$cmd" == *"$ROOT_DIR"* || "$env" == *"$ROOT_DIR"* || "$cwd" == "$ROOT_DIR" || "$cwd" == "$ROOT_DIR"/* ]]; then
          matched=1
        fi
        ;;
    esac

    if [[ "$matched" -eq 1 ]]; then
      pids+=("$pid")
    fi
  done

  if [[ "${#pids[@]}" -gt 0 ]]; then
    echo "Stopping residual MAAT processes: ${pids[*]}"
    kill "${pids[@]}" >/dev/null 2>&1 || true
    for _ in {1..20}; do
      local still_running=()
      for pid in "${pids[@]}"; do
        kill -0 "$pid" >/dev/null 2>&1 && still_running+=("$pid") || true
      done
      [[ "${#still_running[@]}" -eq 0 ]] && break
      sleep 0.2
    done
    for pid in "${pids[@]}"; do
      kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" >/dev/null 2>&1 || true
    done
  fi
}

purge_regenerable_state() {
  echo "Purging MAAT generated documents while keeping the maat directory..."

  local roster_file students_file
  roster_file="$(cfg_value 'cfg.get("student_roster_xlsx_abs", "")' 2>/dev/null || true)"
  students_file="$(cfg_value 'cfg.get("students_csv_abs", "")' 2>/dev/null || true)"

  # Runtime artefacts regenerated by install/start/evaluation.
  rm -rf -- \
    "$ROOT_DIR/runs" \
    "$ROOT_DIR/submissions" \
    "$ROOT_DIR/logs" \
    "$ROOT_DIR/vendor" \
    "$ROOT_DIR/.install-cache" \
    "$ROOT_DIR/__pycache__" \
    "$ROOT_DIR/.pytest_cache" \
    2>/dev/null || true

  find "$ROOT_DIR" -type d -name "__pycache__" -prune -exec rm -rf -- {} + 2>/dev/null || true
  find "$ROOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

  # Project-local state is regenerated by ./manage-maat.sh install/start/evaluation.
  while IFS= read -r -d '' project_state_dir; do
    find "$project_state_dir" -mindepth 1 ! -name students.xlsx ! -name .gitkeep -exec rm -rf -- {} + 2>/dev/null || true
  done < <(find "$ROOT_DIR/projects" -mindepth 2 -maxdepth 2 -type d \( -name results -o -name documents \) -print0 2>/dev/null)

  ensure_dirs
  echo "Uninstall completed. The maat directory was kept:"
  echo "  $ROOT_DIR"
  echo "You can reinstall and restart with: ./manage-maat.sh install"
}

server_info() {
  python_with_vendor - <<'PY'
from pathlib import Path
from maat_app.config import load_config
cfg = load_config()
root = Path(cfg['root_dir'])
print('')
print('=== MAAT - serveur ===')
print(f"Application     : {cfg.get('app_name')}")
print(f"École/module    : {cfg.get('school_name')} | {cfg.get('course_name')}")
print(f"Adresse locale  : http://127.0.0.1:{cfg.get('listen_port', 8000)}")
print(f"Adresse publique: {cfg.get('public_url')}")
print(f"Écoute          : {cfg.get('listen_host')}:{cfg.get('listen_port')}")
print(f"CSV étudiants   : {cfg.get('students_csv_abs')}")
print(f"PDF enseignant  : {Path(cfg.get('documents_dir_abs')) / 'students_tokens_admin.pdf'}")
print(f"PDF coupons     : {Path(cfg.get('documents_dir_abs')) / 'students_tokens_cards.pdf'}")
print(f"Fichier Excel   : {cfg.get('student_roster_xlsx_abs')}")
print(f"Projet actif    : {cfg.get('project_id')} — {cfg.get('project_title')}")
print(f"Langages        : {', '.join(cfg.get('allowed_languages', []))}")
print(f"Données projet  : {cfg.get('data_dir_abs')}")
print(f"Logs serveur    : {root / 'logs' / 'server.log'}")
print(f"Documents projet: {cfg.get('documents_dir_abs')}")
print(f"Résultats projet: {cfg.get('results_dir_abs')}")
print(f"Dossiers runs   : {root / 'runs'}")
mode = "automatique (/proc/cpuinfo)" if cfg.get("automatic_parallel_settings", True) else "manuel (config.json)"
print(f"Parallélisation : {mode}")
print(f"  Dépôts   : {cfg.get('queue_workers')} worker(s)")
for lang_id, profile in cfg.get('language_profiles', {}).items():
    cr = profile.get('compile_resources', {})
    rr = profile.get('run_resources', {})
    print(f"  {lang_id}: image={profile.get('docker_image')} | build CPUs={cr.get('cpus')} | run CPUs={rr.get('cpus')}")
print(f"Admin           : http://127.0.0.1:{cfg.get('listen_port', 8000)}/admin")
print('')
print('Phone notifications with ntfy:')
enabled = bool(cfg.get('tunnel_notifications_enabled', False))
server = str(cfg.get('tunnel_ntfy_server') or 'https://ntfy.sh').rstrip('/')
topic = str(cfg.get('tunnel_ntfy_topic') or '')
print(f"  config.json status : notifications_enabled={'yes' if enabled else 'no'}")
print(f"  ntfy server        : {server}")
print(f"  ntfy topic         : {topic if topic else 'not configured'}")
if enabled and topic:
    print("  Phone setup        : install the ntfy app, add a subscription,")
    print("                       then enter the server and topic shown above.")
    print("                       Keep this topic private.")
elif enabled:
    print("  Required action    : set tunnel.ntfy_topic in config.json.")
else:
    print("  Activation         : set tunnel.notifications_enabled=true and use a non-empty tunnel.ntfy_topic.")
print('==========================')
print('')
PY
}

start_server() {
  warn_if_root
  ensure_dirs
  check_python
  if [[ ! -d "$VENDOR_DIR" ]]; then
    echo "Python dependencies missing. Run: ./manage-maat.sh install" >&2
    exit 1
  fi
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
    echo "Server already running with PID $(cat "$PID_FILE")"
    server_info
    return 0
  fi
  nohup env PYTHONPATH="$VENDOR_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" -m maat_app.app >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
    echo "Error: server did not start. Read logs with: ./manage-maat.sh logs" >&2
    exit 1
  fi
  echo "Server started with PID $(cat "$PID_FILE")."
  server_info
}


ensure_local_secrets() {
  check_python
  python_with_vendor - <<'PYSECRETS'
import json, secrets
from pathlib import Path
from maat_app.json_style import format_value_comment_json
p = Path('config.json')
if not p.exists():
    raise SystemExit(0)
cfg = json.loads(p.read_text(encoding='utf-8'))
server = cfg.setdefault('server', {})
entry = server.setdefault('admin_token', {'value': 'CHANGE_ME', 'comment': 'Secret key required to open the administration page.'})
value = entry.get('value') if isinstance(entry, dict) else entry
if not value or str(value) == 'CHANGE_ME':
    if isinstance(entry, dict):
        entry['value'] = secrets.token_urlsafe(24)
    else:
        server['admin_token'] = {'value': secrets.token_urlsafe(24), 'comment': 'Secret key required to open the administration page.'}
    p.write_text(format_value_comment_json(cfg), encoding='utf-8')
    print('Generated a local admin token in config.json.')
PYSECRETS
}

init_config() {
  check_python
  if [[ -f "$ROOT_DIR/config.json" ]]; then
    echo "config.json already exists."
    ensure_local_secrets
    return 0
  fi
  if [[ ! -f "$ROOT_DIR/config.example.json" ]]; then
    echo "Missing config.example.json" >&2
    exit 1
  fi
  cp "$ROOT_DIR/config.example.json" "$ROOT_DIR/config.json"
  echo "Created config.json from config.example.json"
  ensure_local_secrets
}

list_projects() {
  python_with_vendor - <<'PY'
from pathlib import Path
from maat_app.config import load_config, ROOT
cfg=load_config()
active=Path(cfg['active_project_abs']).resolve()
for p in sorted((ROOT/'projects').glob('*/project.json')):
    pid=p.parent.name
    mark='*' if p.parent.resolve()==active else ' '
    print(f"{mark} {pid}: {p.parent}")
PY
}

set_project() {
  local project_id="${1:-}"
  if [[ -z "$project_id" ]]; then echo "Usage: ./manage-maat.sh set-project <project_id>" >&2; exit 2; fi
  python_with_vendor - "$project_id" <<'PY'
import json, sys
from maat_app.config import ROOT
from maat_app.json_style import format_value_comment_json
pid=sys.argv[1]
project_dir=ROOT/'projects'/pid
if not (project_dir/'project.json').exists():
    raise SystemExit(f"Unknown project: {pid}")
path=ROOT/'config.json'
cfg=json.load(open(path, encoding='utf-8'))
cfg.setdefault('project', {})['active_project']={'value': f'projects/{pid}', 'comment': 'Path to the active MAAT project directory.'}
path.write_text(format_value_comment_json(cfg), encoding='utf-8')
print(f"Active project set to: {pid}")
PY
}

new_project() {
  local project_id="${1:-}"
  if [[ -z "$project_id" ]]; then echo "Usage: ./manage-maat.sh new-project <project_id>" >&2; exit 2; fi
  python_with_vendor - "$project_id" <<'PY'
import json, sys
from maat_app.config import ROOT
from maat_app.json_style import format_value_comment_json
pid=sys.argv[1]
base=ROOT/'projects'/pid
(base/'data').mkdir(parents=True, exist_ok=True)
(base/'statement').mkdir(parents=True, exist_ok=True)
project={
    'project': {
        'id': {'value': pid, 'comment': 'Unique project identifier.'},
        'title': {'value': {'fr': pid, 'en': pid}, 'comment': 'Project title displayed in MAAT.'},
        'description': {'value': {'fr': 'Nouveau projet MAAT.', 'en': 'New MAAT project.'}, 'comment': 'Project description displayed in MAAT.'},
        'allowed_languages': {'value': ['cpp'], 'comment': 'Language profiles accepted for this project.'},
        'default_language': {'value': 'cpp', 'comment': 'Default language used when no language is explicitly selected.'},
    },
    'interface': {
        'school_name': {'value': {'fr': 'Polytech Paris-Saclay', 'en': 'Polytech Paris-Saclay'}, 'comment': 'School name displayed in the web interface and generated documents.'},
        'course_name': {'value': {'fr': 'Plateforme de projets', 'en': 'Project platform'}, 'comment': 'Course name displayed in the web interface and generated documents.'},
        'student_level': {'value': {'fr': 'Version multi-langages', 'en': 'Multi-language version'}, 'comment': 'Student level or subtitle displayed in the web interface and generated documents.'},
    },
    'students': {
        'roster_xlsx_path': {'value': 'documents/students.xlsx', 'comment': 'Path to the project roster workbook relative to this project directory.'},
        'generated_students_csv': {'value': 'documents/students.csv', 'comment': 'CSV file generated from the project roster and used by the server.'},
    },
    'submission_limits': {
        'cooldown_seconds': {'value': 300, 'comment': 'Minimum delay between accepted submissions for one token.'},
        'max_zip_size_mb': {'value': 20, 'comment': 'Maximum uploaded ZIP size in megabytes.'},
        'max_file_count_per_zip': {'value': 100, 'comment': 'Maximum number of entries allowed in one ZIP archive.'},
        'max_uncompressed_size_mb': {'value': 80, 'comment': 'Maximum total uncompressed size accepted from one ZIP archive.'},
        'max_output_bytes': {'value': 200000, 'comment': 'Maximum stdout/stderr bytes kept and displayed per stream.'},
    },
    'teaching_session': {
        'timer_enabled': {'value': True, 'comment': 'Enable or disable the teaching-session countdown and submission deadline.'},
        'duration_minutes': {'value': 240, 'comment': 'Duration of the teaching session in minutes when the timer is enabled.'},
        'snapshot_interval_minutes': {'value': 30, 'comment': 'Interval between automatic leaderboard snapshots.'},
        'snapshot_directory': {'value': 'results/snapshots', 'comment': 'Directory where leaderboard snapshots are written, relative to this project directory.'},
    },
    'directories': {
        'documents_directory': {'value': 'documents', 'comment': 'Project-local directory where MAAT stores documents, rosters, tokens and SQLite state.'},
        'results_directory': {'value': 'results', 'comment': 'Project-local directory where MAAT writes leaderboards, snapshots and exports.'},
    },
    'data': {
        'data_directory': {'value': 'data', 'comment': 'Project data directory relative to this project directory.'},
        'instances_pattern': {'value': 'instance_*.txt', 'comment': 'Glob pattern selecting evaluation instances.'},
        'support_files': {'value': [], 'comment': 'Additional project data files mounted read-only beside the instances.'},
    },
    'scoring': {
        'primary_metric': {'value': 'score', 'comment': 'Metric used for ranking.'},
        'metrics': {'value': [{'name':'score','label':{'fr':'Score','en':'Score'},'regex':'score\s*(?:->|:)\s*([-+]?\d+(?:\.\d+)?)','type':'float','aggregation':'sum','higher_is_better':True,'precision':3}], 'comment': 'Metrics parsed from stdout.'},
        'output_format': {'value': 'score -> <number>', 'comment': 'Expected stdout format displayed to students.'},
    },
}
(base/'project.json').write_text(format_value_comment_json(project), encoding='utf-8')
(base/'statement'/'README.md').write_text('# ' + pid + '\n', encoding='utf-8')
print(f"Created project skeleton: {base}")
PY
}

build_sample_submissions() {
  check_core_tools
  local project_dir sample_dir output

  project_dir="$ROOT_DIR/projects/tsp"
  sample_dir="$project_dir/sample_solution"
  output="$project_dir/tsp_cpp_sample_submission.zip"
  if [[ -f "$sample_dir/src/main.cpp" ]]; then
    rm -f "$output"
    (cd "$sample_dir" && zip -qr "$output" src/main.cpp)
    echo "Generated $output"
  fi

  project_dir="$ROOT_DIR/projects/mnist_digits"
  sample_dir="$project_dir/sample_solution"
  output="$project_dir/mnist_python_sample_submission.zip"
  if [[ -f "$sample_dir/main.py" ]]; then
    rm -f "$output"
    (cd "$sample_dir" && zip -qr "$output" main.py)
    echo "Generated $output"
  fi
}

case "$mode" in
  install)
    warn_if_root
    ensure_dirs
    install_python_deps
    init_config
    ensure_local_secrets
    autotune_parallelism
    extract_students
    generate_students_pdf
    print_students_table
    ensure_docker
    build_docker_image
    python_with_vendor -m maat_app.diagnostics || true
    start_server
    ;;
  check|doctor)
    warn_if_root
    ensure_dirs
    check_python
    python_with_vendor scripts/check_maat.py "${@:2}"
    ;;
  uninstall)
    "$0" stop || true
    stop_tunnel_if_present
    kill_residual_maat_processes
    stop_maat_docker_containers
    purge_regenerable_state
    exit 0
    ;;
  start)
    start_server
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      pid="$(cat "$PID_FILE")"
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" || true
        for _ in {1..20}; do
          if ! kill -0 "$pid" >/dev/null 2>&1; then break; fi
          sleep 0.2
        done
        if kill -0 "$pid" >/dev/null 2>&1; then kill -9 "$pid" || true; fi
        echo "Server stopped."
      fi
      rm -f "$PID_FILE"
    else
      echo "Server is not running."
    fi
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  logs)
    ensure_dirs
    touch "$LOG_FILE"
    tail -f "$LOG_FILE"
    ;;
  list-projects)
    list_projects
    ;;
  set-project)
    set_project "${2:-}"
    ;;
  new-project)
    new_project "${2:-}"
    ;;
  build-runners)
    check_python
    ensure_docker
    ensure_dirs
    build_docker_image
    ;;
  build-samples)
    build_sample_submissions
    ;;
  init-config)
    init_config
    ;;
  *)
    echo "Unknown mode: $mode" >&2
    echo "Usage: $0 {install|check|doctor|uninstall|start|stop|restart|logs|list-projects|set-project|new-project|build-runners|build-samples|init-config}" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$ROOT_DIR/config.json"
LOG_FILE="$ROOT_DIR/logs/tunnel.log"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

project_documents_dir() {
  PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}" "$PYTHON_BIN" - <<'PY_DOC_DIR'
from pathlib import Path
from maat_app.config import load_config, ROOT
try:
    print(load_config().get("documents_dir_abs") or str(ROOT / "documents"))
except Exception:
    print(str(ROOT / "documents"))
PY_DOC_DIR
}

DOCUMENTS_DIR="$(project_documents_dir)"
PID_FILE="$DOCUMENTS_DIR/tunnel.pid"
WATCH_PID_FILE="$DOCUMENTS_DIR/tunnel_watch.pid"
URL_FILE="$DOCUMENTS_DIR/tunnel_url.txt"
SHORT_URL_FILE="$DOCUMENTS_DIR/tunnel_short_url.txt"

usage() {
  cat >&2 <<USAGE
Usage: $0 {start|stop|restart|logs|watch}

Modes:
  start       start a Cloudflare quick tunnel to the MAAT server
  stop        stop the Cloudflare tunnel started by this script
  restart     restart the Cloudflare tunnel
  logs        follow tunnel logs
  watch       start the tunnel and recreate it if the public URL stops responding
USAGE
}

mode="${1:-}"
if [[ -z "$mode" ]]; then
  usage
  exit 2
fi

ensure_dirs() {
  mkdir -p logs "$DOCUMENTS_DIR"
}

cfg_value() {
  local section="$1"
  local key="$2"
  local default="${3:-}"
  "$PYTHON_BIN" - "$CONFIG_FILE" "$section" "$key" "$default" <<'PY'
import json
import sys
from pathlib import Path

config_path, section, key, default = sys.argv[1:5]
cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
value = cfg.get(section, {}).get(key, default)
# Backward-compatible read for old local config copies and for the current
# {"value": ..., "comment": ...} config entries.
if isinstance(value, dict):
    if "value" in value:
        value = value["value"]
        if isinstance(value, dict):
            value = value.get("fr", value.get("en", default))
    elif "value_fr" in value:
        value = value["value_fr"]
    elif "value_en" in value:
        value = value["value_en"]
print(value)
PY
}

cfg_bool() {
  local section="$1"
  local key="$2"
  local default="${3:-false}"
  local value
  value="$(cfg_value "$section" "$key" "$default")"
  case "${value,,}" in
    1|true|yes|on|y|oui) return 0 ;;
    *) return 1 ;;
  esac
}

local_url() {
  local host port
  host="$(cfg_value server listen_host 127.0.0.1)"
  port="$(cfg_value server listen_port 8000)"
  case "$host" in
    ""|"0.0.0.0"|"::"|"[::]") host="127.0.0.1" ;;
  esac
  printf 'http://%s:%s' "$host" "$port"
}

check_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command '$1' not found." >&2
    exit 1
  fi
}

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1
}

shorten_url() {
  local url="$1"
  local short_url="$url"
  if command -v curl >/dev/null 2>&1; then
    short_url="$(curl -fsS "https://ulvis.net/api.php?url=${url}" 2>/dev/null || printf '%s' "$url")"
  fi
  printf '%s' "$short_url"
}

print_share_url() {
  local short_url="$1"
  printf -- "\n\033[1;32m-------------------------------------------------------------------------\n"
  printf -- "SERVER URL TO SHARE WITH STUDENTS -> %s\n" "$short_url"
  printf -- "-------------------------------------------------------------------------\033[0m\n\n"
}

print_ntfy_phone_info() {
  local server topic enabled
  server="$(cfg_value tunnel ntfy_server 'https://ntfy.sh')"
  topic="$(cfg_value tunnel ntfy_topic '')"
  server="${server%/}"

  printf -- "\n\033[1;36m-------------------------------------------------------------------------\n"
  printf -- "PHONE NOTIFICATIONS WITH NTFY\n"
  printf -- "-------------------------------------------------------------------------\033[0m\n"

  if cfg_bool tunnel notifications_enabled false; then
    enabled="yes"
  else
    enabled="no"
  fi

  printf -- "config.json status : notifications_enabled=%s\n" "$enabled"
  printf -- "ntfy server        : %s\n" "$server"
  if [[ -n "$topic" ]]; then
    printf -- "ntfy topic         : %s\n" "$topic"
  else
    printf -- "ntfy topic         : not configured\n"
  fi

  if [[ "$enabled" == "yes" && -n "$topic" ]]; then
    printf -- "\nOn your phone:\n"
    printf -- "  1. Install the ntfy app.\n"
    printf -- "  2. Open the app and add a subscription.\n"
    printf -- "  3. Enter the server shown above, then the topic shown above.\n"
    printf -- "  4. Keep this topic private: anyone who knows it can receive the notifications.\n"
    printf -- "\nA notification is sent whenever a new tunnel URL is published.\n\n"
  elif [[ "$enabled" == "yes" ]]; then
    printf -- "\nNotifications are enabled, but no ntfy topic is defined in config.json.\n\n"
  else
    printf -- "\nNotifications are disabled. To enable them, set tunnel.notifications_enabled=true and use a non-empty tunnel.ntfy_topic.\n\n"
  fi
}

notify_url() {
  local short_url="$1"
  local raw_url="$2"
  local server topic title message

  if ! cfg_bool tunnel notifications_enabled false; then
    return 0
  fi

  server="$(cfg_value tunnel ntfy_server 'https://ntfy.sh')"
  topic="$(cfg_value tunnel ntfy_topic '')"
  title="$(cfg_value tunnel ntfy_title 'MAAT tunnel')"

  if [[ -z "$topic" ]]; then
    echo "warning: ntfy notifications are enabled but tunnel.ntfy_topic is empty." >&2
    return 0
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "warning: curl not found; ntfy notification skipped." >&2
    return 0
  fi

  server="${server%/}"
  message="Nouvelle URL MAAT : ${short_url}"
  curl -fsS \
    -H "Title: ${title}" \
    -H "Tags: link" \
    -d "$message" \
    "${server}/${topic}" >/dev/null 2>&1 \
    || echo "warning: ntfy notification failed for ${server}/${topic}." >&2
}

publish_url() {
  local public_url="$1"
  local notify="${2:-no}"
  local short_url
  short_url="$(shorten_url "$public_url")"
  printf '%s\n' "$public_url" > "$URL_FILE"
  printf '%s\n' "$short_url" > "$SHORT_URL_FILE"
  print_share_url "$short_url"
  print_ntfy_phone_info
  if [[ "$notify" == "notify" ]]; then
    notify_url "$short_url" "$public_url"
  fi
}

wait_for_public_url() {
  local public_url=""
  for _ in {1..60}; do
    if ! is_running; then
      echo "error: cloudflared stopped before publishing a URL. Read logs with: ./manage-tunnel.sh logs" >&2
      exit 1
    fi
    public_url="$(grep -Eo 'https://[-a-z0-9.]+\.trycloudflare\.com' "$LOG_FILE" | tail -n 1 || true)"
    if [[ -n "$public_url" ]]; then
      printf '%s' "$public_url"
      return 0
    fi
    sleep 1
  done
  return 1
}

start_tunnel() {
  local notify="${1:-no}"
  ensure_dirs
  check_command cloudflared
  check_command grep
  check_command curl

  if is_running; then
    echo "Cloudflare tunnel already running with PID $(cat "$PID_FILE")."
    if [[ -f "$URL_FILE" ]]; then
      publish_url "$(cat "$URL_FILE")" "$notify"
    fi
    return 0
  fi

  : > "$LOG_FILE"
  rm -f "$URL_FILE" "$SHORT_URL_FILE"
  local url public_url
  url="$(local_url)"
  echo "+ Starting Cloudflare tunnel for ${url}"
  echo "+ Waiting for the public trycloudflare.com URL..."

  nohup cloudflared tunnel --protocol http2 --url "$url" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  if public_url="$(wait_for_public_url)"; then
    publish_url "$public_url" "$notify"
    return 0
  fi

  echo "warning: tunnel started with PID $(cat "$PID_FILE"), but no public URL was found yet." >&2
  echo "Read logs with: ./manage-tunnel.sh logs" >&2
}

stop_tunnel() {
  local stop_watch="${1:-no}"
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" || true
      for _ in {1..20}; do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
          break
        fi
        sleep 0.2
      done
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" || true
      fi
      echo "Cloudflare tunnel stopped."
    else
      echo "Cloudflare tunnel is not running."
    fi
    rm -f "$PID_FILE" "$URL_FILE" "$SHORT_URL_FILE"
  else
    echo "Cloudflare tunnel is not running."
  fi

  if [[ "$stop_watch" == "yes" && -f "$WATCH_PID_FILE" ]]; then
    local watcher_pid
    watcher_pid="$(cat "$WATCH_PID_FILE")"
    if [[ -n "$watcher_pid" && "$watcher_pid" != "$$" ]] && kill -0 "$watcher_pid" >/dev/null 2>&1; then
      kill "$watcher_pid" || true
      for _ in {1..20}; do
        if ! kill -0 "$watcher_pid" >/dev/null 2>&1; then
          break
        fi
        sleep 0.2
      done
      if kill -0 "$watcher_pid" >/dev/null 2>&1; then
        kill -9 "$watcher_pid" || true
      fi
      echo "Cloudflare tunnel watcher stopped."
    fi
    rm -f "$WATCH_PID_FILE"
  fi
}

url_is_alive() {
  local url="$1"
  local timeout code
  timeout="$(cfg_value tunnel watch_url_timeout_seconds 10)"
  [[ -n "$url" ]] || return 1
  code="$(curl -L -sS -o /dev/null -w '%{http_code}' --max-time "$timeout" "$url" 2>/dev/null || printf '000')"
  case "$code" in
    2*|3*) return 0 ;;
    *) return 1 ;;
  esac
}

watch_tunnel() {
  local interval_minutes interval_seconds current_url
  ensure_dirs
  check_command curl

  interval_minutes="$(cfg_value tunnel watch_interval_minutes 5)"
  if ! [[ "$interval_minutes" =~ ^[0-9]+$ ]] || [[ "$interval_minutes" -lt 1 ]]; then
    echo "warning: invalid tunnel.watch_interval_minutes=$interval_minutes; using 5." >&2
    interval_minutes=5
  fi
  interval_seconds=$((interval_minutes * 60))

  printf '%s\n' "$$" > "$WATCH_PID_FILE"
  trap 'echo; echo "Stopping tunnel watcher..."; stop_tunnel no; rm -f "$WATCH_PID_FILE"; exit 0' INT TERM EXIT

  start_tunnel notify
  echo "+ Watching tunnel URL every ${interval_minutes} minute(s)."

  while true; do
    sleep "$interval_seconds"
    if ! is_running || [[ ! -f "$URL_FILE" ]]; then
      echo "+ Tunnel process or URL file missing; recreating tunnel..."
      stop_tunnel no || true
      start_tunnel notify
      continue
    fi
    current_url="$(cat "$URL_FILE")"
    if url_is_alive "$current_url"; then
      echo "+ $(date '+%Y-%m-%d %H:%M:%S') - tunnel OK: $current_url"
    else
      echo "+ $(date '+%Y-%m-%d %H:%M:%S') - tunnel URL unavailable; recreating tunnel..."
      stop_tunnel no || true
      start_tunnel notify
    fi
  done
}

case "$mode" in
  start)
    start_tunnel notify
    ;;
  stop)
    stop_tunnel yes
    ;;
  restart)
    stop_tunnel yes
    start_tunnel notify
    ;;
  logs)
    ensure_dirs
    touch "$LOG_FILE"
    tail -f "$LOG_FILE"
    ;;
  watch)
    watch_tunnel
    ;;
  *)
    echo "Unknown mode: $mode" >&2
    usage
    exit 2
    ;;
esac

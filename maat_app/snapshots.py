from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path
import threading
from typing import TYPE_CHECKING

from .leaderboard import best_by_group

if TYPE_CHECKING:
    from .storage import Storage


def maybe_write_leaderboard_snapshot(storage: 'Storage') -> None:
    cfg = storage.cfg
    interval = max(1, int(cfg.get('snapshot_interval_minutes', 30))) * 60
    state_file = Path(cfg.get('documents_dir_abs', Path(cfg['active_project_abs']) / 'documents')) / 'last_leaderboard_snapshot.txt'
    now = time.time()
    try:
        last = float(state_file.read_text(encoding='utf-8').strip()) if state_file.exists() else 0.0
    except ValueError:
        last = 0.0
    if now - last < interval:
        return
    out_dir = Path(cfg.get('snapshot_directory_abs', Path(cfg['results_dir_abs']) / 'snapshots'))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = out_dir / f'leaderboard_snapshot_{stamp}.html'
    rows = best_by_group(storage)
    parts = ['<!doctype html><meta charset="utf-8"><title>MAAT leaderboard snapshot</title>', '<style>body{font-family:sans-serif}table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #ccc;padding:.35rem .6rem}</style>']
    parts.append(f'<h1>MAAT leaderboard snapshot - {html.escape(stamp)}</h1>')
    for group, group_rows in rows.items():
        parts.append(f'<h2>{html.escape(group)}</h2><table><thead><tr><th>Rank</th><th>Symbole</th><th>Student</th><th>Heuristic</th><th>Score</th><th>Submission</th></tr></thead><tbody>')
        for row in group_rows:
            parts.append('<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in [row.get('rank',''), row.get('animal',''), f"{row.get('first_name','')} {row.get('last_name','')}", row.get('heuristic_name',''), row.get('score_total',''), row.get('submission_id','')]) + '</tr>')
        parts.append('</tbody></table>')
    path.write_text('\n'.join(parts), encoding='utf-8')
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(str(now), encoding='utf-8')


_worker_started = False
_worker_lock = threading.Lock()


def start_snapshot_worker(storage: 'Storage') -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    def loop() -> None:
        while True:
            try:
                maybe_write_leaderboard_snapshot(storage)
            except Exception:
                pass
            interval = max(1, int(storage.cfg.get('snapshot_interval_minutes', 30))) * 60
            time.sleep(interval)
    thread = threading.Thread(target=loop, name='maat-snapshot-worker', daemon=True)
    thread.start()

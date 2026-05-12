from __future__ import annotations

import queue
import threading
import time
from typing import Any

from .evaluator import Evaluator
from .leaderboard import export_leaderboards
from .storage import Storage


class EvaluationQueue:
    def __init__(self, cfg: dict[str, Any], storage: Storage):
        self.cfg = cfg
        self.storage = storage
        self.jobs: queue.Queue[str] = queue.Queue()
        self.workers: list[threading.Thread] = []
        self.started = False
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
            worker_count = max(1, int(self.cfg.get("queue_workers", 1)))
            for index in range(worker_count):
                worker = threading.Thread(target=self._loop, name=f"maat-worker-{index + 1}", daemon=True)
                self.workers.append(worker)
                worker.start()
            self.recover_queued_jobs()

    def recover_queued_jobs(self) -> None:
        for status in self.storage.list_statuses():
            if status.get("status") == "queued":
                self.enqueue(status["submission_id"])
            elif status.get("status") == "running":
                status["status"] = "internal_error"
                status["message"] = "Evaluation interrupted by a server shutdown. Submit again if needed."
                status["message_key"] = "interrupted_msg"
                status["message_args"] = {}
                status["current_container_name"] = None
                self.storage.save_status(status["submission_id"], status)

    def enqueue(self, submission_id: str) -> None:
        self.jobs.put(submission_id)

    def position(self, submission_id: str) -> int | None:
        with self.jobs.mutex:
            queue_items = list(self.jobs.queue)
        visible_items = [sid for sid in queue_items if not self.storage.is_canceled(sid)]
        if submission_id not in visible_items:
            return None
        return visible_items.index(submission_id) + 1

    def _loop(self) -> None:
        evaluator = Evaluator(self.cfg, self.storage)
        while True:
            submission_id = self.jobs.get()
            try:
                if not self.storage.is_canceled(submission_id):
                    evaluator.evaluate(submission_id)
                    export_leaderboards(self.storage)
            finally:
                self.jobs.task_done()
                time.sleep(0.1)

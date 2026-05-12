from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .storage import Storage


def _primary_metric(storage: Storage) -> dict[str, Any]:
    name = str(storage.cfg.get("primary_metric", "score"))
    for metric in storage.cfg.get("project_metrics", []) or []:
        if str(metric.get("name")) == name:
            return metric
    return {"name": name, "higher_is_better": True}


def _metric_value(row: dict[str, Any], name: str) -> Any:
    return (row.get("metrics") or {}).get(name, row.get(name, row.get("score_total")))


def _sort_value(value: Any, higher: bool) -> float:
    try:
        val = float(value)
    except Exception:
        val = float("-inf") if higher else float("inf")
    return -val if higher else val


def add_aggregate_metrics(status: dict[str, Any]) -> None:
    metrics = status.setdefault("metrics", {}) or {}
    if status.get("score_total") is not None:
        metrics.setdefault("score", status.get("score_total"))
    status["metrics"] = metrics


def best_by_group(storage: Storage, group: str | None = None) -> dict[str, list[dict[str, Any]]]:
    metric = _primary_metric(storage)
    primary = str(metric.get("name", "score"))
    higher = bool(metric.get("higher_is_better", True))
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for status in storage.list_statuses():
        if status.get("status") != "done" or status.get("cancel_requested") or status.get("canceled_at"):
            continue
        add_aggregate_metrics(status)
        value = (status.get("metrics") or {}).get(primary, status.get("score_total"))
        if value is None:
            continue
        status_group = str(status.get("group", ""))
        if group and status_group != group:
            continue
        token = str(status.get("token", ""))
        groups.setdefault(status_group, {})
        previous = groups[status_group].get(token)
        if previous is None or _sort_value(value, higher) < _sort_value((previous.get("metrics") or {}).get(primary, previous.get("score_total")), higher):
            status["score_total"] = value
            groups[status_group][token] = status
    result: dict[str, list[dict[str, Any]]] = {}
    for group_name, rows_by_token in groups.items():
        rows = list(rows_by_token.values())
        rows.sort(key=lambda row: (_sort_value((row.get("metrics") or {}).get(primary, row.get("score_total")), higher), str(row.get("last_name", "")), str(row.get("first_name", ""))))
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
        result[group_name] = rows
    return result


def best_by_instance_group(storage: Storage, group: str | None = None) -> dict[str, list[dict[str, Any]]]:
    metric = _primary_metric(storage)
    primary = str(metric.get("name", "score"))
    higher = bool(metric.get("higher_is_better", True))
    grouped: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for status in storage.list_statuses():
        if status.get("status") != "done" or status.get("cancel_requested") or status.get("canceled_at"):
            continue
        status_group = str(status.get("group", ""))
        if group and status_group != group:
            continue
        token = str(status.get("token", ""))
        grouped.setdefault(status_group, {})
        for instance_row in status.get("instances", []) or []:
            if instance_row.get("status") != "OK":
                continue
            value = (instance_row.get("metrics") or {}).get(primary, instance_row.get("score"))
            if value is None:
                continue
            instance = str(instance_row.get("instance", ""))
            if not instance:
                continue
            grouped[status_group].setdefault(instance, {})
            candidate = dict(status)
            candidate.update({"instance": instance, "score": value, "metrics": instance_row.get("metrics", {}), "runtime_seconds": instance_row.get("runtime_seconds")})
            previous = grouped[status_group][instance].get(token)
            if previous is None or _sort_value(value, higher) < _sort_value(previous.get("score"), higher):
                grouped[status_group][instance][token] = candidate
    result: dict[str, list[dict[str, Any]]] = {}
    for group_name, by_instance in grouped.items():
        rows: list[dict[str, Any]] = []
        for instance_name in sorted(by_instance, key=natural_key):
            instance_rows = list(by_instance[instance_name].values())
            instance_rows.sort(key=lambda row: (_sort_value(row.get("score"), higher), str(row.get("last_name", "")), str(row.get("first_name", ""))))
            for idx, row in enumerate(instance_rows, start=1):
                row["rank"] = idx
                rows.append(row)
        result[group_name] = rows
    return result


def natural_key(value: str) -> list[Any]:
    parts = re.split(r"(\d+)", value.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def export_leaderboards(storage: Storage) -> None:
    results_dir = Path(storage.cfg["results_dir_abs"])
    results_dir.mkdir(parents=True, exist_ok=True)
    metric_names = [str(m.get("name")) for m in storage.cfg.get("project_metrics", []) or []]
    for group, rows in best_by_group(storage).items():
        fieldnames = ["rank", "group", "symbol", "last_name", "first_name", "heuristic_name", "language", "submission_id", *metric_names, "valid_instances", "failed_instances", "total_instances", "total_runtime_seconds", "submitted_at"]
        with (results_dir / f"leaderboard_{group}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                csv_row = {key: row.get(key, "") for key in fieldnames}
                csv_row["symbol"] = row.get("animal", "")
                for name in metric_names:
                    csv_row[name] = (row.get("metrics") or {}).get(name, row.get(name, ""))
                writer.writerow(csv_row)

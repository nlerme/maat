from __future__ import annotations

import io
from datetime import datetime
from typing import Any


def submission_report_pdf(status: dict[str, Any], metric_defs: list[dict[str, Any]] | None = None) -> bytes:
    """Return a small self-contained PDF report without external dependencies."""
    metric_defs = metric_defs or []
    lines: list[str] = []
    sid = status.get("public_id") or status.get("submission_id", "")
    lines.append(f"MAAT - Submission report #{sid}")
    lines.append(f"Generated at: {datetime.now().strftime('%d-%m-%Y @ %H:%M:%S')}")
    lines.append("")
    lines.append(f"Project: {status.get('project_title') or status.get('project_id') or ''}")
    lines.append(f"Language: {status.get('language','')}")
    lines.append(f"Student: {status.get('first_name','')} {status.get('last_name','')} {status.get('animal','')}")
    lines.append(f"Group: {status.get('group','')}")
    lines.append(f"Approach: {status.get('heuristic_name','')}")
    lines.append(f"Status: {status.get('status','')}")
    lines.append(f"Submitted at: {status.get('submitted_at','')}")
    lines.append(f"Finished at: {status.get('finished_at','') or status.get('canceled_at','') or ''}")
    lines.append("")
    metrics = status.get("metrics") or {}
    if metric_defs:
        for metric in metric_defs:
            name = str(metric.get("name", ""))
            label = metric.get("label")
            if isinstance(label, dict):
                label = label.get("fr") or label.get("en") or name
            lines.append(f"{label or name}: {_fmt(metrics.get(name, status.get(name)))}")
    else:
        lines.append(f"Score total: {_fmt(status.get('score_total'))}")
    lines.append(f"Instances ok: {status.get('valid_instances', 0)}/{status.get('total_instances', 0)}")
    lines.append(f"Instances failed: {status.get('failed_instances', 0)}/{status.get('total_instances', 0)}")
    lines.append(f"Total runtime: {_fmt(status.get('total_runtime_seconds'))} s")
    lines.append("")
    lines.append("Instances")
    lines.append("-" * 80)
    for item in status.get("instances", []) or []:
        metric_parts = []
        for metric in metric_defs:
            name = str(metric.get("name", ""))
            metric_parts.append(f"{name}={_fmt((item.get('metrics') or {}).get(name, item.get(name)))}")
        lines.append(f"{item.get('instance','')} | {item.get('status','')} | {' | '.join(metric_parts)} | time={_fmt(item.get('runtime_seconds'))}s")
    return _simple_pdf(lines)


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        if isinstance(value, float):
            return f"{value:.6g}"
    except Exception:
        pass
    return str(value)


def _simple_pdf(lines: list[str]) -> bytes:
    page_width, page_height = 595, 842
    margin_x, y0, line_h = 42, 800, 13
    lines_per_page = 56
    pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)] or [[]]
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = []
    for idx in range(len(pages)):
        page_obj = 4 + 2 * idx
        kids.append(f"{page_obj} 0 R")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for idx, page_lines in enumerate(pages):
        page_obj = 4 + 2 * idx
        content_obj = page_obj + 1
        stream = _content_stream(page_lines, margin_x, y0, line_h)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>".encode("ascii"))
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode("ascii"))
        out.write(obj)
        out.write(b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return out.getvalue()


def _content_stream(lines: list[str], margin_x: int, y0: int, line_h: int) -> bytes:
    commands = ["BT", "/F1 10 Tf", f"{margin_x} {y0} Td"]
    for idx, line in enumerate(lines):
        text = _escape_pdf_text(_wrap(line, 110))
        if idx:
            commands.append(f"0 -{line_h} Td")
        commands.append(f"({text}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", errors="replace")


def _wrap(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _escape_pdf_text(text: str) -> str:
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

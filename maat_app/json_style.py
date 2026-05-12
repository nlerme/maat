from __future__ import annotations

import json
from typing import Any


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def format_value_comment_json(data: dict[str, Any]) -> str:
    """Format MAAT editable JSON files with section-level spacing.

    Root attributes are displayed as airy sections; internal value/comment
    attributes are kept on one line with optional alignment for readability.
    """
    lines: list[str] = ["{"]
    items = list(data.items())
    for section_index, (section, body) in enumerate(items):
        root_comma = "," if section_index < len(items) - 1 else ""
        lines.append(f"  {json.dumps(section, ensure_ascii=False)}:")
        if isinstance(body, dict) and body and all(isinstance(value, dict) and "value" in value and "comment" in value for value in body.values()):
            lines.append("  {")
            max_key_len = max(len(json.dumps(key, ensure_ascii=False)) for key in body)
            children = list(body.items())
            for child_index, (key, value) in enumerate(children):
                child_comma = "," if child_index < len(children) - 1 else ""
                key_text = json.dumps(key, ensure_ascii=False)
                padding = " " * (max_key_len - len(key_text) + 1)
                lines.append(f"    {key_text}:{padding}{_compact(value)}{child_comma}")
            lines.append(f"  }}{root_comma}")
        else:
            block = json.dumps(body, ensure_ascii=False, indent=2)
            block_lines = ["  " + line for line in block.splitlines()]
            if block_lines:
                block_lines[-1] += root_comma
            lines.extend(block_lines)
    lines.append("}")
    return "\n".join(lines) + "\n"

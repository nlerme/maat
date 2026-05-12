#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import random
import re
import string
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OUTPUT_COLUMNS = ["group", "last_name", "first_name", "token", "animal", "animal_entity"]
TOKEN_ALPHABET = string.ascii_uppercase + string.digits
TOKEN_LENGTH = 16

# Symbol/nature emoji list.  Every entry must be a single Unicode code point so
# the PDF generator can find a unique PNG asset and never render an empty box.
ANIMAL_EMOJIS = [
    '🐵', '🐒', '🦍', '🦧', '🐶', '🐕', '🐩', '🐺', '🦊', '🦝',
    '🐱', '🐈', '🦁', '🐯', '🐅', '🐆', '🐴', '🐎', '🦄', '🦓',
    '🦌', '🦬', '🐮', '🐂', '🐃', '🐄', '🐷', '🐖', '🐗', '🐽',
    '🐏', '🐑', '🐐', '🐪', '🐫', '🦙', '🦒', '🐘', '🦣', '🦏',
    '🦛', '🐭', '🐁', '🐀', '🐹', '🐰', '🐇', '🦫', '🦔', '🦇',
    '🐻', '🐨', '🐼', '🦥', '🦦', '🦨', '🦘', '🦡', '🐾', '🦃',
    '🐔', '🐓', '🐣', '🐤', '🐥', '🐦', '🐧', '🦅', '🦆', '🦢',
    '🦉', '🦤', '🪶', '🦩', '🦚', '🦜', '🪿', '🐸', '🐊', '🐢',
    '🦎', '🐍', '🐲', '🐉', '🦕', '🦖', '🐳', '🐋', '🐬', '🦭',
    '🐟', '🐠', '🐡', '🦈', '🐙', '🐚', '🪸', '🪼', '🐌', '🦋',
    '🐛', '🐜', '🐝', '🪲', '🐞', '🦗', '🪳', '🦂', '🦟', '🪰',
    '🪱', '🦠'
]

GROUP_ALIASES = {"groupe", "group", "grp", "td", "tp", "classe", "promotion"}
LAST_NAME_ALIASES = {"nom", "nom usuel", "lastname", "last name", "surname", "family name"}
FIRST_NAME_ALIASES = {"prenom", "prénom", "prenom usuel", "prénom usuel", "firstname", "first name", "given name"}
HEADER_ALIASES = GROUP_ALIASES | LAST_NAME_ALIASES | FIRST_NAME_ALIASES
GROUP_RE = re.compile(r"^(?:g(?:roupe)?|td|tp|classe)?\s*[-_ ]?[a-z0-9]{1,4}$", re.IGNORECASE)


def strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")


def norm_text(value: str) -> str:
    return " ".join(strip_accents(value or "").strip().casefold().split())


def clean_cell(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").strip().split())


def col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + (ord(char.upper()) - 64)
    return value - 1


def parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in si.iter() if node.tag == f"{NS_MAIN}t") for si in root.findall(f"{NS_MAIN}si")]


def workbook_sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
    rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target: dict[str, str] = {}
    for rel in rel_root.findall(f"{PKG_REL}Relationship"):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            rid_to_target[rel_id] = target.lstrip("/")
    result: dict[str, str] = {}
    sheets_node = workbook_root.find(f"{NS_MAIN}sheets")
    if sheets_node is None:
        return result
    for sheet in sheets_node:
        name = sheet.attrib.get("name")
        rel_id = sheet.attrib.get(f"{NS_REL}id")
        if not name or not rel_id or rel_id not in rid_to_target:
            continue
        target = rid_to_target[rel_id]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        result[name] = target
    return result


def read_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[dict[int, str]]:
    root = ET.fromstring(zf.read(sheet_path))
    sheet_data = root.find(f"{NS_MAIN}sheetData")
    if sheet_data is None:
        return []
    rows: list[dict[int, str]] = []
    for row in sheet_data.findall(f"{NS_MAIN}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{NS_MAIN}c"):
            idx = col_to_index(cell.attrib.get("r", ""))
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter() if node.tag == f"{NS_MAIN}t")
            else:
                value_node = cell.find(f"{NS_MAIN}v")
                if value_node is None or value_node.text is None:
                    value = ""
                elif cell_type == "s":
                    value = shared_strings[int(value_node.text)]
                else:
                    value = value_node.text
            values[idx] = clean_cell(value)
        rows.append(values)
    return rows


def header_role(value: str) -> str | None:
    key = norm_text(value)
    if key in GROUP_ALIASES:
        return "group"
    if key in LAST_NAME_ALIASES:
        return "last_name"
    if key in FIRST_NAME_ALIASES:
        return "first_name"
    return None


def detect_header_map(rows: list[dict[int, str]]) -> tuple[int, dict[str, int]] | None:
    for row_index, row in enumerate(rows):
        mapping: dict[str, int] = {}
        for col_index, text in row.items():
            role = header_role(text)
            if role is not None:
                mapping[role] = col_index
        if {"group", "last_name", "first_name"}.issubset(mapping):
            return row_index, mapping
    return None


def is_group_like(value: str) -> bool:
    text = clean_cell(value)
    key = norm_text(text)
    if not text or key in HEADER_ALIASES:
        return False
    if len(text) > 24:
        return False
    return bool(GROUP_RE.match(text)) or bool(re.match(r"^[A-Z]{1,4}\d{1,3}$", text, flags=re.IGNORECASE))


def is_person_name_like(value: str) -> bool:
    text = clean_cell(value)
    key = norm_text(text)
    if not text or key in HEADER_ALIASES:
        return False
    if len(text) < 2 or len(text) > 80:
        return False
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", text))


def valid_student_row(row: dict[int, str], mapping: dict[str, int]) -> bool:
    group = row.get(mapping["group"], "")
    last_name = row.get(mapping["last_name"], "")
    first_name = row.get(mapping["first_name"], "")
    return is_group_like(group) and is_person_name_like(last_name) and is_person_name_like(first_name)


def infer_column_map(rows: list[dict[int, str]]) -> dict[str, int]:
    columns = sorted({col for row in rows for col, value in row.items() if clean_cell(value)})
    best: tuple[float, dict[str, int], list[int]] | None = None
    for group_col in columns:
        for last_col in columns:
            if last_col == group_col:
                continue
            for first_col in columns:
                if first_col in {group_col, last_col}:
                    continue
                mapping = {"group": group_col, "last_name": last_col, "first_name": first_col}
                valid_indices = [idx for idx, row in enumerate(rows) if valid_student_row(row, mapping)]
                if len(valid_indices) < 2:
                    continue
                group_values = [norm_text(rows[idx].get(group_col, "")) for idx in valid_indices]
                distinct_groups = sorted(set(group_values))
                distinct_last = len({norm_text(rows[idx].get(last_col, "")) for idx in valid_indices})
                distinct_first = len({norm_text(rows[idx].get(first_col, "")) for idx in valid_indices})
                if not distinct_groups or len(distinct_groups) > max(12, len(valid_indices) // 2):
                    continue
                if distinct_last < max(2, len(valid_indices) // 4) or distinct_first < max(2, len(valid_indices) // 4):
                    continue
                adjacency_bonus = 2.0 if sorted(mapping.values()) == list(range(min(mapping.values()), max(mapping.values()) + 1)) else 0.0
                group_dup_bonus = len(valid_indices) / max(1, len(distinct_groups))
                score = len(valid_indices) * 10.0 + group_dup_bonus + adjacency_bonus - len(distinct_groups)
                if best is None or score > best[0]:
                    best = (score, mapping, valid_indices)
    if best is None:
        raise RuntimeError("Could not infer group/name/first-name columns in the workbook")
    return best[1]


def parse_rows_with_mapping(rows: list[dict[int, str]], mapping: dict[str, int], start_row: int = 0) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    for row in rows[start_row:]:
        if not valid_student_row(row, mapping):
            continue
        group = clean_cell(row.get(mapping["group"], ""))
        last_name = clean_cell(row.get(mapping["last_name"], ""))
        first_name = clean_cell(row.get(mapping["first_name"], ""))
        extracted.append({"group": group, "last_name": last_name, "first_name": first_name})
    return extracted


def parse_sheet(rows: list[dict[int, str]]) -> list[dict[str, str]]:
    header = detect_header_map(rows)
    if header is not None:
        header_index, mapping = header
        parsed = parse_rows_with_mapping(rows, mapping, header_index + 1)
        if parsed:
            return parsed
    mapping = infer_column_map(rows)
    return parse_rows_with_mapping(rows, mapping, 0)


def student_key(group: str, last_name: str, first_name: str) -> str:
    return "|".join([norm_text(group), norm_text(last_name), norm_text(first_name)])


def deterministic_token(seed: int, key: str, used: set[str], length: int = TOKEN_LENGTH) -> str:
    counter = 0
    while True:
        digest = hashlib.sha256(f"{seed}|{counter}|{key}".encode("utf-8")).digest()
        chars = []
        for byte in digest:
            chars.append(TOKEN_ALPHABET[byte % len(TOKEN_ALPHABET)])
            if len(chars) == length:
                break
        token = "".join(chars)
        if token not in used:
            used.add(token)
            return token
        counter += 1


def emoji_entity(emoji: str) -> str:
    return "".join(f"&#x{ord(char):X};" for char in emoji)


def is_single_symbol(emoji: str) -> bool:
    return bool(emoji) and len(emoji) == 1 and "\u200d" not in emoji and "\ufe0f" not in emoji


def read_existing_students(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        result: dict[str, dict[str, str]] = {}
        for row in reader:
            group = row.get("group", "")
            last_name = row.get("last_name", "")
            first_name = row.get("first_name", "")
            if group and last_name and first_name:
                result[student_key(group, last_name, first_name)] = row
        return result


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", norm_text(value))]


def read_roster_rows(xlsx_path: Path) -> list[dict[str, str]]:
    if not zipfile.is_zipfile(xlsx_path):
        raise RuntimeError(f"Unsupported roster file format: {xlsx_path}. Please provide an .xlsx file.")
    all_rows: list[dict[str, str]] = []
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings = parse_shared_strings(zf)
        sheet_paths = workbook_sheet_paths(zf)
        if not sheet_paths:
            raise RuntimeError("No worksheet found in the roster workbook")
        sheet_errors: list[str] = []
        for sheet_name, sheet_path in sheet_paths.items():
            rows = read_sheet_rows(zf, sheet_path, shared_strings)
            if not any(rows):
                continue
            try:
                parsed = parse_sheet(rows)
            except Exception as exc:
                sheet_errors.append(f"{sheet_name}: {exc}")
                continue
            all_rows.extend(parsed)
    if not all_rows:
        detail = "; ".join(sheet_errors) if sheet_errors else "no non-empty sheet"
        raise RuntimeError(f"No student found in the roster workbook ({detail})")
    # Remove duplicate lines while preserving first occurrence.
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in all_rows:
        key = student_key(row["group"], row["last_name"], row["first_name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(key=lambda row: (natural_key(row["group"]), norm_text(row["last_name"]), norm_text(row["first_name"])))
    return unique


def extract(xlsx_path: Path, seed: int, existing_csv: Path | None = None) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows = read_roster_rows(xlsx_path)
    if len(rows) > len(ANIMAL_EMOJIS):
        raise RuntimeError(f"Not enough symbol emojis: {len(rows)} students for {len(ANIMAL_EMOJIS)} symbols")

    existing = read_existing_students(existing_csv) if existing_csv is not None else {}
    used_tokens = {row.get("token", "") for row in existing.values() if len((row.get("token") or "").strip()) == TOKEN_LENGTH}
    used_animals = {row.get("animal", "") for row in existing.values() if is_single_symbol(row.get("animal", ""))}

    animals = [emoji for emoji in ANIMAL_EMOJIS if is_single_symbol(emoji)]
    rng.shuffle(animals)
    animal_iter = (animal for animal in animals if animal not in used_animals)

    result: list[dict[str, str]] = []
    current_tokens: set[str] = set()
    current_animals: set[str] = set()
    for row in rows:
        key = student_key(row["group"], row["last_name"], row["first_name"])
        old = existing.get(key, {})
        token = (old.get("token") or "").strip()
        if len(token) == TOKEN_LENGTH and token not in current_tokens:
            used_tokens.add(token)
        else:
            token = deterministic_token(seed, key, used_tokens)
        current_tokens.add(token)
        old_animal = old.get("animal", "")
        if is_single_symbol(old_animal) and old_animal not in current_animals:
            animal = old_animal
        else:
            animal = next(animal_iter)
        current_animals.add(animal)
        result.append(
            {
                "group": row["group"],
                "last_name": row["last_name"],
                "first_name": row["first_name"],
                "token": token,
                "animal": animal,
                "animal_entity": emoji_entity(animal),
            }
        )
    return result


def write_rows(rows: Iterable[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: Sequence[str]) -> tuple[Path, Path, int]:
    # New simplified format: extract_students_from_xlsx.py <xlsx-file> <output.csv> [seed]
    # Legacy compatibility: extract_students_from_xlsx.py <xlsx-file> <sheet=group,...> <output.csv> [seed]
    if len(argv) in (4, 5) and "=" in argv[2]:
        seed = int(argv[4]) if len(argv) == 5 else 20262026
        return Path(argv[1]).resolve(), Path(argv[3]).resolve(), seed
    if len(argv) in (3, 4):
        seed = int(argv[3]) if len(argv) == 4 else 20262026
        return Path(argv[1]).resolve(), Path(argv[2]).resolve(), seed
    print("Usage: extract_students_from_xlsx.py <xlsx-file> <output.csv> [seed]", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    xlsx_path, output, seed = parse_args(sys.argv)
    write_rows(extract(xlsx_path, seed, output), output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="$SCRIPT_DIR/tsp_cpp_sample_submission.zip"
TMP_DIR="$SCRIPT_DIR/.tmp_tsp_submission"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR/src"
cp "$PROJECT_DIR/sample_solution/src/main.cpp" "$TMP_DIR/src/main.cpp"
rm -f "$OUTPUT"
python3 - "$TMP_DIR" "$OUTPUT" <<'PY'
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1])
out = Path(sys.argv[2])
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    zf.write(root / 'src' / 'main.cpp', 'src/main.cpp')
PY
rm -rf "$TMP_DIR"
echo "Created: $OUTPUT"

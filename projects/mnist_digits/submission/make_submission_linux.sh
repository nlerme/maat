#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="$SCRIPT_DIR/mnist_python_sample_submission.zip"
TMP_DIR="$SCRIPT_DIR/.tmp_mnist_submission"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp "$PROJECT_DIR/sample_solution/main.py" "$TMP_DIR/main.py"
rm -f "$OUTPUT"
python3 - "$TMP_DIR" "$OUTPUT" <<'PY'
import sys, zipfile
from pathlib import Path
root = Path(sys.argv[1])
out = Path(sys.argv[2])
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    zf.write(root / 'main.py', 'main.py')
PY
rm -rf "$TMP_DIR"
echo "Created: $OUTPUT"

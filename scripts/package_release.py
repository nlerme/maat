from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PARTS = {'vendor', '.install-cache', '__pycache__', '.pytest_cache'}
EXCLUDED_RUNTIME_ROOTS = {'runs', 'submissions', 'logs'}
EXCLUDED_DOC_FILES = {'server.pid', 'counter.txt', 'token_clients.json', 'cooldown_unlocks.json', 'submissions_paused.json'}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if rel.parts and rel.parts[0] in EXCLUDED_RUNTIME_ROOTS:
        return path.name == '.gitkeep'
    if len(rel.parts) >= 3 and rel.parts[0] == 'projects' and rel.parts[2] in {'results'}:
        return path.name == '.gitkeep'
    if len(rel.parts) >= 3 and rel.parts[0] == 'projects' and rel.parts[2] == 'documents':
        return path.name in {'.gitkeep', 'students.xlsx'}
    if path.suffix in {'.pyc'}:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    output = Path(args.output or ROOT.parent / f'maat_v{version}.zip')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in ROOT.rglob('*') if p.is_file()):
            if include(path):
                zf.write(path, Path('maat') / path.relative_to(ROOT))
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

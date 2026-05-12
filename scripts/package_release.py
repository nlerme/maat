from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PARTS = {'vendor', '.install-cache', '__pycache__', '.pytest_cache', '.venv'}
EXCLUDED_RUNTIME_ROOTS = {'runs', 'submissions', 'logs'}
EXCLUDED_ROOT_FILES = {'config.json'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo'}
EXCLUDED_NAMES = {'server.pid', 'counter.txt', 'token_clients.json', 'cooldown_unlocks.json', 'submissions_paused.json', 'last_leaderboard_snapshot.txt'}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_ROOT_FILES:
        return False
    if any(part in EXCLUDED_PARTS for part in parts):
        return False
    if parts[0] in EXCLUDED_RUNTIME_ROOTS:
        return path.name == '.gitkeep'
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if path.suffix == '.zip':
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    if len(parts) >= 3 and parts[0] == 'projects' and parts[2] == 'results':
        return path.name == '.gitkeep'
    if len(parts) >= 3 and parts[0] == 'projects' and parts[2] == 'documents':
        return path.name in {'.gitkeep', 'students.xlsx'}
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description='Create a clean public MAAT release ZIP.')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    output = Path(args.output or ROOT.parent / f'maat_v{version}.zip')
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in ROOT.rglob('*') if p.is_file()):
            if include(path):
                zf.write(path, Path('maat') / path.relative_to(ROOT))
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

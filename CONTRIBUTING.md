# Contributing

Keep MAAT simple: one active project, declarative project profiles, declarative language profiles, explicit Docker limits and clear user-facing messages.

## Local setup

```bash
./manage-maat.sh init-config
./manage-maat.sh install
./manage-maat.sh check
```

## JSON style

Teacher-edited JSON files must keep the airy `value` / `comment` format used by `config.example.json` and `projects/*/project.json`: root sections on separate blocks, internal attributes on one line, English-only comments.

## Adding a project

Add `projects/<id>/project.json`, `projects/<id>/data/`, `projects/<id>/documents/students.xlsx` and optionally `projects/<id>/statement/` and `projects/<id>/sample_solution/`.

## Adding a language

Add `languages/<id>/language.json` and `docker/<id>-runner/Dockerfile`. The profile must declare accepted extensions, entrypoints, build/run commands, forbidden patterns and Docker resources.

## Release hygiene

Before packaging, run:

```bash
python3 scripts/check_maat.py --public-release
./scripts/make_release_zip.sh
```

Avoid hidden project-specific assumptions in `evaluator.py`, `leaderboard.py` and `reports.py`. Project behavior should come from `project.json`; language behavior should come from `language.json`.

# Contributing

Keep MAAT simple: one active project, declarative language profiles, explicit Docker limits and clear user-facing messages.

## Adding a project

Add `projects/<id>/project.json`, `projects/<id>/data/` and optionally `projects/<id>/statement/` and `projects/<id>/sample_solution/`. Prefer the `value` / `comment` style in files edited by teachers.

## Adding a language

Add `languages/<id>/language.json` and `docker/<id>-runner/Dockerfile`. The profile must declare accepted extensions, entrypoints, build/run commands, forbidden patterns and Docker resources.

## Style

Avoid hidden project-specific assumptions in `evaluator.py`, `leaderboard.py` and `reports.py`. Project behavior should come from `project.json`; language behavior should come from `language.json`.

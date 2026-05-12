# Changelog

## 11.0.0-alpha

- Prepared the first public-preview source bundle.
- Kept `config.example.json` as the versioned configuration template and made `config.json` local-only.
- Added `init-config`, `build-samples`, public-release hygiene checks and release ZIP packaging.
- Added full status legends on history, leaderboard, administration and submission pages.
- Harmonized block content typography.
- Updated the TSP C++ sample to print instance characteristics, the distance matrix, iterative tour-length progress and a final metric line.
- Updated the MNIST-like Python sample to print instance characteristics, algorithm parameters, accuracy progress and a final metric line.

## 10.0.0

- Introduced one active project selected from `projects/<project_id>`.
- Added declarative project profiles with data files, instances, metrics and ranking policy.
- Added declarative language profiles for C++, Python and Java.
- Added Docker runner images for C++, Python and Java.
- Generalized build commands, run commands, stdout parsing, leaderboard columns, CSV exports and PDF reports.
- Added example project `tsp` for C++ and example project `mnist_digits` for Python digit classification.
- Added release-oriented files: `LICENSE`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.gitignore`, JSON schemas and a packaging script.

## 9.x

- Stabilized the C++-only MAAT workflow.

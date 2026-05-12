# MAAT v11 alpha

MAAT is a lightweight, single-machine teaching platform for collecting ZIP submissions, building/running student code inside Docker, extracting metrics from stdout and publishing leaderboards during a practical session.

This preview release keeps the teacher-controlled workflow simple: **one active project**, declarative project profiles, declarative language profiles, Docker runner images, configurable metrics and reusable example projects.

## What MAAT is

MAAT is designed for supervised practical sessions on a teacher-controlled machine. It helps collect submissions, evaluate them consistently, display results, export a session archive and demonstrate different project formats through reusable examples.

## What MAAT is not

MAAT is not a public multi-tenant judge, not a SaaS platform, not a Moodle replacement, not a large-scale contest platform and not an infallible security sandbox.

## Quick start

```bash
./manage-maat.sh init-config
./manage-maat.sh install
./manage-maat.sh check
./manage-maat.sh start
```

The server uses `config.json`. Public releases only ship `config.example.json`; `init-config` creates the local `config.json` and generates a local admin token when needed.

## Configuration files

- `config.example.json`: versioned template committed to the repository.
- `config.json`: local active configuration, generated from `config.example.json`, ignored by Git and not included in public release ZIPs.
- `projects/<project_id>/project.json`: project-level teaching configuration: title, accepted languages, data, metrics, roster path, submission limits and timer.
- `languages/<language_id>/language.json`: language profile: extensions, Docker image, build command, run command, forbidden patterns and resource limits.

Teacher-edited JSON files use the `value` / `comment` style:

```json
"active_project": {"value": "projects/tsp", "comment": "Path to the active MAAT project directory."}
```

Root sections are intentionally formatted as readable blocks, and comments must remain in English.

## Repository layout

```text
maat_app/          Flask app, evaluation logic, reports, storage and configuration loading
scripts/           checks, packaging and student-document generation helpers
templates/         Flask/Jinja templates
static/            CSS and JavaScript
translations/      generic MAAT UI translations
docker/            Docker runner build contexts
languages/         language profiles
projects/          example projects and project-local configuration
schemas/           JSON schemas for configuration/profile files
```

## Included example projects

### `projects/tsp` — C++ / Traveling Salesman Problem

Input: text files containing `n` followed by an `n x n` distance matrix.

The sample C++ solution prints instance characteristics, the full distance matrix, iterative progress and a final metric line:

```text
iteration <k> tour length -> <current_best>
final tour length -> <number>
```

Metric: `tour_length`, aggregated over instances, **lower is better**.

### `projects/mnist_digits` — Python / digit classification

Input: CSV files containing rows `label,p0,...,p63` for small MNIST-like handwritten digit images. The project includes a read-only `train_digits.csv` support file and public/private test files.

The sample Python solution prints instance characteristics, algorithm parameters, accuracy progress checkpoints and a final metric line:

```text
final accuracy -> <percentage>
```

Metric: `accuracy`, averaged over instances, **higher is better**.

The dataset is generated from scikit-learn's offline handwritten-digits dataset: it is MNIST-like, 8x8 grayscale, text-based, split approximately 2/3 training and 1/3 test, and does not require network downloads.

## Selecting a project

```bash
./manage-maat.sh list-projects
./manage-maat.sh set-project tsp
./manage-maat.sh set-project mnist_digits
```

Changing the active project switches the project data, roster, documents, SQLite database, results, metrics, languages and snapshots.

## Creating a new project

```bash
./manage-maat.sh new-project my_project
./manage-maat.sh set-project my_project
./manage-maat.sh check
```

Then edit `projects/my_project/project.json`, add instances in `projects/my_project/data/`, choose one or more languages in `allowed_languages`, and define the stdout metrics in `scoring.metrics`.

A project is expected to contain:

```text
projects/<id>/project.json
projects/<id>/data/
projects/<id>/documents/students.xlsx
projects/<id>/results/
projects/<id>/sample_solution/        optional
projects/<id>/statement/README.md     optional
```

## Adding a language profile

Create:

```text
languages/<language_id>/language.json
docker/<language_id>-runner/Dockerfile
```

The language profile declares accepted extensions, entrypoints, the Docker image, build/run commands, forbidden source patterns and compile/run resources. Run:

```bash
./manage-maat.sh build-runners
```

C++ and Python are demonstrated by the bundled projects. Java is included as an **experimental** profile in this preview release; add a Java project before treating it as stable.

## Sample submissions

Generated ZIP submissions are not committed in the public release. Regenerate them locally with:

```bash
./manage-maat.sh build-samples
```

This creates:

```text
projects/tsp/tsp_cpp_sample_submission.zip
projects/mnist_digits/mnist_python_sample_submission.zip
```

## Student ZIP format

The ZIP must contain the entrypoint expected by the selected language profile.

C++ example:

```text
submission.zip
└── src/
    └── main.cpp
```

Python example:

```text
submission.zip
└── main.py
```

If several languages are allowed by a project, MAAT can infer the language when the ZIP is unambiguous; ambiguous multi-language submissions are rejected with a clear error.

## Administration during a practical session

The admin page lets the teacher monitor submissions, view detailed logs, pause/resume submissions, export the session archive and inspect the effective project configuration. `manage-maat.sh start` prints the local admin URL and the configured public URL.

## Export and archival

Session artefacts are project-local:

```text
projects/<project_id>/documents/
projects/<project_id>/results/
```

The admin export includes the effective configuration, project profile, language profiles, results, useful logs and generated reports. Runtime artefacts are ignored by Git and excluded from public release ZIPs.

## Docker runners

Runner Dockerfiles are stored in:

```text
docker/cpp-runner/Dockerfile
docker/python-runner/Dockerfile
docker/java-runner/Dockerfile
```

Build all runner images:

```bash
./manage-maat.sh build-runners
```

`./manage-maat.sh install` also builds missing or changed runner images.

## Security and limits

MAAT executes untrusted code. Docker improves isolation but must not be considered a perfect security boundary.

Containers are launched with network disabled, dropped Linux capabilities, `no-new-privileges`, a non-root user, PID/CPU/RAM limits, timeouts, a read-only root filesystem and a tmpfs `/tmp`.

Source filtering blocks obvious dangerous patterns such as shell execution, process creation, network imports and destructive filesystem APIs. This is a pedagogical defense-in-depth layer and does not replace Docker.

Do not expose MAAT as a hostile public multi-tenant service without a stronger isolation layer such as gVisor, nsjail or virtual machines.

## ntfy phone notifications

Tunnel notifications can be enabled in local `config.json`:

```json
"notifications_enabled": {"value": true, "comment": "Enable ntfy notifications for tunnel status changes."}
```

Install the ntfy app on your phone, subscribe to the configured topic, and keep the topic private.

## Checks

General check:

```bash
./manage-maat.sh check
```

Public-release hygiene check:

```bash
python3 scripts/check_maat.py --public-release
```

The public-release check verifies that local configuration, secrets, runtime artefacts and generated ZIPs are absent.

## Packaging a public release ZIP

```bash
./scripts/make_release_zip.sh --output maat_v11.0.0-alpha.zip
```

The generated ZIP excludes `config.json`, runtime artefacts, generated reports, generated student CSV files, SQLite databases, logs and generated sample submission ZIPs.

## Tested environment

This preview bundle has been syntax-checked and locally exercised in the ChatGPT execution environment. Docker was not available there; run `./manage-maat.sh check --strict` on a real Linux machine with Docker before using MAAT in a session.

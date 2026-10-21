# Contributing and development

[Back to the project](README.md) · [User guide](docs/USAGE.md) · [Website and screenshots](docs/PAGES.md)

Runtime and development dependencies are fully pinned with hashes. Regenerate them after editing the corresponding `.in` file:

```bash
python -m pip install pip-tools
python -m piptools compile --upgrade --generate-hashes --strip-extras -o requirements.txt requirements.in
python -m piptools compile --upgrade --generate-hashes --strip-extras -o requirements-dev.txt requirements-dev.in
```

Run the quality gates with:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
ruff check modules tests
pytest --cov --cov-report=term-missing --cov-fail-under=60
pip-audit -r requirements.txt --disable-pip
docker compose -f compose.yml config --quiet
docker compose -f compose-testing.yml config --quiet
```

For a local container build and Web UI:

```bash
./start-kmm.sh
```

Open `http://localhost:8765`. The script rebuilds the image and starts the development container in the background using `compose-testing.yml` and the Compose project `kmm-dev`. Run it again after changing code to rebuild and restart. Both scripts work from any working directory and require Docker Compose v2.

To stop development:

```bash
./stop-kmm.sh
```

Configuration, account, audit history, and caches remain in `./config`.

## Kubernetes

See `k8s-manifest/README.md`. Kubernetes credentials are stored in a Secret generated locally and are not committed.

## Releases

Add English release notes under `## [Unreleased]` in `CHANGELOG.md` as changes are made, then commit all changes on `main`. From a clean working tree, run:

```bash
./scripts/release.sh
```

The script calculates `YYYY.W.N` (ISO year, week without a leading zero, and a weekly counter), taking local tags, remote tags, and `VERSION` into account. It updates `VERSION`, turns the unreleased notes into a dated release section, reopens an empty Unreleased section, creates a release commit and annotated tag, and pushes both atomically to `origin`. An empty changelog, dirty working tree, or branch other than `main` is rejected. Do not manually bump `VERSION` or create dated release headings.

The Forgejo pipeline runs quality checks, verifies that the tag matches `VERSION` and has release notes, and builds the versioned Docker image and `latest`. Images include `VERSION`, `CHANGELOG.md`, and the MIT `LICENSE`, with OCI version, revision, and license labels. The application reads the packaged `VERSION` for startup logs and the Web UI footer. Running the release script publishes to the configured remote and triggers this pipeline.

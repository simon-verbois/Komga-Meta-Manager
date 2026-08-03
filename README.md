<p align="center">
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=flat" alt="GitHub Last Commit" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/stargazers"><img src="https://img.shields.io/github/stars/simon-verbois/Komga-Meta-Manager?style=flat&color=yellow" alt="GitHub Stars" height="28"/></a>
</p>

# Komga Meta Manager

Komga Meta Manager enriches Komga manga metadata from AniList, with optional translation, persistent caches, scheduled runs and discovery of newly added series.

## Features

- AniList title matching with configurable confidence threshold
- Summary, genres, status, authors, score tag, AniList link and cover management
- Safe dry-run mode and granular update/removal flags
- Google Translate or DeepL translation with manual overrides
- Daily scheduler and new-series watcher
- Docker, Compose and Kubernetes deployment

## Quick start

```bash
git clone https://github.com/simon-verbois/Komga-Meta-Manager.git
cd Komga-Meta-Manager
cp config/config.yml.template config/config.yml
$EDITOR config/config.yml
docker compose up
```

The complete configuration is documented in `config/config.yml.template`. Keep `system.dry_run: true` for the first execution and review the proposed changes before enabling writes.

Secrets can stay in `config.yml` for backward compatibility, or be injected with environment variables:

- `KMM_KOMGA_API_KEY`
- `KMM_DEEPL_API_KEY`

Environment variables take priority over YAML values.

## Processing behavior

- `overwrite_existing: false` fills empty scalar fields. Score tags and AniList links are merged with existing values.
- `force_unlock: false` preserves locked metadata.
- Every `remove_fields` flag defaults to `false`; removal is always explicit.
- Covers are added only when no user-uploaded cover exists, unless `overwrite_existing` is enabled.
- Replacing a cover never deletes previous uploads. Explicit cover removal deletes only `USER_UPLOADED` thumbnails.
- AniList adult results are excluded from automatic matching.

The process exits with a non-zero status when configuration, initialization or a run-once processing operation fails. Scheduled mode stays alive after an individual failed run and reports the failure in logs.

## Development

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

For a local container build and one-shot run:

```bash
docker compose -f compose-testing.yml build
docker compose -f compose-testing.yml up
```

## Kubernetes

See `k8s-manifest/README.md`. Kubernetes credentials are stored in a Secret generated locally and are not committed.

## License and disclaimer

Licensed under the terms in `LICENSE`. This is a personal automation project shared as-is, without warranty or guarantee of maintenance.

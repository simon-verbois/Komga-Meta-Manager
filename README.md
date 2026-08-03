<p align="center">
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=flat" alt="GitHub Last Commit" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/stargazers"><img src="https://img.shields.io/github/stars/simon-verbois/Komga-Meta-Manager?style=flat&color=yellow" alt="GitHub Stars" height="28"/></a>
</p>

# Komga Meta Manager

Komga Meta Manager enriches Komga manga metadata from AniList, MangaDex or MangaUpdates, with optional translation, persistent caches, scheduled runs and discovery of newly added series.

## Features

- AniList, MangaDex and MangaUpdates metadata providers
- Multilingual and alternate-title matching with configurable confidence threshold
- Summary, original publisher, genres, status, authors, score tag, provider link and cover management
- Safe dry-run mode and granular update/removal flags
- Google Translate or DeepL translation with persistent caching
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

- `overwrite_existing: false` fills empty scalar fields, including the original publisher supplied by MangaUpdates. Score tags and provider links are merged with existing values.
- Publisher selection keeps MangaUpdates entries marked `Original`, ignores translated licensees, and joins multiple original publishers with a comma.
- `force_unlock: false` preserves locked metadata.
- Every `remove_fields` flag defaults to `false`; removal is always explicit.
- `remove_fields.language: true` clears the language stored on each series.
- `remove_fields.reading_direction: true` clears the reading direction stored on each series.
- Covers are added only when no user-uploaded cover exists, unless `overwrite_existing` is enabled.
- Replacing a cover never deletes previous uploads. Explicit cover removal deletes only `USER_UPLOADED` thumbnails.
- Adult results are excluded from matching unless `allow_adult` is enabled for that provider.
  MangaDex ratings `erotica` and `pornographic` are both treated as adult.
- Link updates synchronize AniList, MangaDex and MangaUpdates links for every provider that matched, while preserving third-party links. Link removal deletes all three managed links.

## Metadata providers and matching

All providers are active. They are searched by ascending priority; when the first match lacks an enabled metadata field, the next provider fills that field without replacing higher-priority data:

```yaml
providers:
  - name: "anilist"
    priority: 1
    min_score: 80
    allow_adult: false
    preferred_language: "en"
    cache:
      ttl_hours: 168
  - name: "mangadex"
    priority: 2
    min_score: 80
    allow_adult: false
    preferred_language: "en"
    cache:
      ttl_hours: 168
  - name: "mangaupdates"
    priority: 3
    min_score: 80
    allow_adult: false
    preferred_language: "en"
    cache:
      ttl_hours: 168
```

The matcher uses the edited Komga metadata title first and falls back to the series name. It compares every title and alias returned by the provider; exact normalized matches take priority, then a conservative fuzzy score and provider popularity decide the result. A short title occurring inside a longer, different title is not considered a strong match.

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

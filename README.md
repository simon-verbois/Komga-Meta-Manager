<p align="center">
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=flat" alt="GitHub Last Commit" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/stargazers"><img src="https://img.shields.io/github/stars/simon-verbois/Komga-Meta-Manager?style=flat&color=yellow" alt="GitHub Stars" height="28"/></a>
</p>

# Komga Meta Manager

Komga Meta Manager enriches Komga manga metadata from AniList, MangaDex or MangaUpdates, with optional translation, persistent caches, scheduled runs and discovery of newly added series.

## Features

- **Integrated Web UI** on port 8765 with first-run setup wizard and password authentication
- **Hot configuration management**: edit system, Komga, providers, processing and translation settings directly from the Web UI with instant reload (no container restart required)
- **Komga library discovery**: automatically list libraries and enable or disable metadata changes for each library
- **Live controls**: dedicated "Dry Run" simulation, a Dry-Run toggle with safety warnings, and manual "Run Now" execution
- **Dual log viewers**: real-time execution log (with debug toggle) and persistent audit log
- **i18n-ready architecture**: English interface by default, structured for easy locale additions
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
docker compose up -d
```

Open `http://localhost:8765` in your browser:

1. **First-run setup**: create your administrator account on the initial visit.
2. **Configure Komga**: enter your Komga server URL and API key. Libraries load automatically; check the libraries you want to modify and save. Use Refresh libraries to discover newly added libraries, which remain disabled until selected and saved.
3. **Customize settings**: configure providers, matching thresholds, update/removal fields, and translation.
4. **Control execution**: use Dry Run to simulate a job, Run Now to run with the saved dry-run setting, or configure the daily scheduler and watcher. With both disabled, the app waits for manual runs; saving configuration does not start a job. Changes apply to subsequent jobs; an active job finishes with its configuration snapshot.

All configuration is stored in `/config/webui.db`. If an existing `config/config.yml` is present, it is automatically migrated on first startup. During legacy YAML migration, secrets can also be injected via environment variables:

- `KMM_KOMGA_API_KEY`
- `KMM_DEEPL_API_KEY`

Environment variables take priority over YAML values during that one-time import. Afterwards, manage API keys in the Web UI. Back up the `/config` directory to preserve the database, account, audit history, and caches.

Enable Debug Logging under System to collect DEBUG execution messages, then select Show Debug in the log viewer. Debug logging is disabled by default. The interface is English, with UI text centralized in `modules/webui/i18n.py`. Styles and HTMX load from public CDNs, so browser access to those CDNs is required.

## Processing behavior

- Only libraries checked under Configuration → Komga are processed by manual runs, the scheduler and the watcher. Existing library selections are preserved, including when discovery fails. Uncheck all and save to disable all processing. An active job finishes with its existing configuration; subsequent runs use the new selection.
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

The Web UI stays available when a processing job or watcher initialization fails. Check Execution Log for failures and Audit Log for user actions.

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

## License and disclaimer

Licensed under the terms in `LICENSE`. This is a personal automation project shared as-is, without warranty or guarantee of maintenance.

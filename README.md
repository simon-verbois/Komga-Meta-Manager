<p align="center">
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=flat" alt="GitHub Last Commit" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/stargazers"><img src="https://img.shields.io/github/stars/simon-verbois/Komga-Meta-Manager?style=flat&color=yellow" alt="GitHub Stars" height="28"/></a>
</p>

# Komga Meta Manager

Komga Meta Manager enriches Komga manga metadata from AniList, MangaDex or MangaUpdates, with optional translation, persistent caches, scheduled runs and discovery of newly added series.

## Features

- **Fetch → Review → Publish**: KMM fetches metadata into its own catalogue, shows every change as before/after values in **Review**, and writes to Komga only when you publish
- **Persistent job queue**: serial execution for manual, scheduled and watcher jobs; cancel, stop, force stop or run a job again from Activity
- **Integrated Web UI** on port 8765 with first-run setup wizard and password authentication
- **Guided settings**: default metadata rules and sources that every library inherits, per-library customization, automation and translation, all from the Web UI with instant reload
- **Komga library discovery**: automatically list libraries and enable or disable metadata changes for each library
- **Readable activity**: job outcomes in plain language, a persistent history of actions, and a technical log for troubleshooting
- **i18n-ready architecture**: English interface by default, structured for easy locale additions
- AniList, MangaDex and MangaUpdates metadata providers
- Multilingual and alternate-title matching with configurable confidence threshold
- Summary, original publisher, genres, status, authors, score tag, provider link and cover management
- Safe defaults: per-field rules (leave, fill in, clear), existing values and Komga locks preserved unless you choose otherwise
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

1. **Create your account** on the first visit.
2. **Connect to Komga**: enter the server address and an API key, then use **Test connection**.
3. **Choose your libraries** on Home, set their content type, and select **Save and fetch metadata**. KMM fills its own catalogue; Komga is not modified.
4. **Review** the proposed changes: compare Komga's value with the new one, discard what you do not want, and edit anything by hand from **Libraries**.
5. **Publish** all changes or a selection to Komga.

Saving settings never starts a job. Each job keeps the settings and libraries it was started with.

All configuration is stored in `/config/webui.db`. If an existing `config/config.yml` is present, it is automatically migrated on first startup. During legacy YAML migration, secrets can also be injected via environment variables:

- `KMM_KOMGA_API_KEY`
- `KMM_DEEPL_API_KEY`

**Activity → Jobs** lists every job with what it did (Fetch, Publish, or Fetch and publish), its libraries, status and result. Home shows the job in progress. Jobs run in FIFO order, one isolated worker process at a time, without Redis or another service.

- **Cancel** removes a waiting job. **Stop** asks a running job to exit after its current series. **Force stop** kills a blocked worker after confirmation. Changes already sent to Komga remain.
- **Run again** creates a new job with the original settings and libraries. To use corrected settings, start a new fetch or publish instead.
- Waiting jobs persist in `/config/webui.db` and resume after restart. A job interrupted by shutdown is marked **Interrupted** and must be run again explicitly.
- The queue accepts up to 100 waiting jobs. The watcher queues only newly detected series and respects included libraries and skipped series.

Environment variables take priority over YAML values during that one-time import. Afterwards, manage API keys in the Web UI. Back up the `/config` directory to preserve the database, account, audit history, and caches.

**Activity → History** records sign-ins, settings changes, edits and jobs in plain sentences. **Activity → Technical log** shows live output for troubleshooting; select any combination of **DEBUG**, **INFO**, **WARNING**, **ERROR** and **CRITICAL** (your browser remembers the selection). Each job's full log, including debug lines, is kept with the job and can be downloaded. The interface is English, with UI text centralized in `modules/webui/i18n.py`. Styles, scripts and HTMX are served locally; the browser does not need access to external CDNs. Shared interface components and interaction conventions are documented in [design-system/README.md](design-system/README.md).

## Processing behavior

- Libraries **included in automatic runs** are processed by the daily run, the watcher and **Fetch metadata** on Home. Any library can still be fetched from its own page. Already queued or active jobs keep their original library selection.
- Fetching never writes to Komga. Changes wait in **Review** until you publish them, unless **Settings → Automation → Publish to Komga automatically** is selected for automatic runs. Configurations saved before this option existed keep automatic live publishing if they used both phases with simulation off.
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

### Using KMM

**Home** shows what needs attention: changes waiting for review, the job in progress, and each library with its series count, changes to review and last fetch. On first use it asks which libraries to manage.

**Libraries** lists series (or individual books for ebook libraries) with search, filters (changes to review, missing summary, locked fields, skipped) and sorting. Select a card to open the editor panel beside the list; use the arrows to move to the previous or next item. **Save** stores your edit in KMM, where it waits in Review. Edited fields are locked in Komga when published, unless you uncheck the option. **Fetch again from sources** asks the sources again for one series or book; **Replace my edits** is required to overwrite your manual values. **Skip when fetching** leaves a series alone in future fetches.

Each library has three tabs: **Series/Books**, **Metadata sources**, and **Settings**. Metadata sources has its own Save button for source order and options. Settings holds inclusion in automatic runs, content type, metadata rules and summary translation. Saving either tab preserves the other tab's settings. Rules and sources follow **Settings → Defaults** until you change them for that library; **Use defaults** returns to inheritance. Dedicated ebook metadata sources are not implemented.

Under **Metadata rules → Book titles in Komga**, optionally replace displayed book titles with `Volume 1`, `Chapter 1`, the series title, or a custom template using `{series}` and `{number}`. The presets use English; use a custom template for other languages, for example `Tome {number}` or `Chapitre {number}`. Choose number padding such as `01` or `001`. Save, then fetch the library: proposed titles wait in **Review** before publishing, even when all metadata sources are disabled. This option replaces existing titles independently of the policy for other existing values, follows the library's locked-field policy, and preserves manual KMM edits unless you explicitly replace those edits. Missing metadata numbers are skipped rather than inferred from file order. Keep the default **Keep current titles** for ebooks with individual book names; the series-title option gives all books in a series the same title. File names and embedded file metadata are never changed, and no filesystem mount is needed. Changing or disabling the option does not discard previously pending title changes; review or discard those separately.

Metadata rules choose, per field, **Leave**, **Fill in** from the sources, or **Clear**. Two policies apply to all fields: keep existing values or replace them with source values, and respect or override fields locked in Komga. Sources are tried from top to bottom; later sources fill what earlier ones missed.

**Review** groups unpublished changes into collapsible series with change counts. Series metadata is separate from compact book rows ordered by book number; title changes appear directly in each book row. Expand a book to compare all its fields before and after publication, including covers, and open long summaries to read them in full. Expand or collapse all series to scan a large batch. Discard one field or a whole series to keep Komga's value. **Publish all to Komga** or select series to publish only those. Changes Komga rejects stay in Review.

**Settings** has four tabs: **Connection** (address, API key, certificate check, connection test), **Defaults** (rules and sources), **Automation** (daily fetch, new-series watcher, and whether automatic fetches wait for review or publish directly) and **Translation** (service, API key, default language and whether summaries are translated by default; each library can override it).

Back up `/config/webui.db` to preserve the local catalogue, manual edits and history.

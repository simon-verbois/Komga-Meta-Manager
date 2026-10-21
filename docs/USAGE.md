# Using Komga Meta Manager

[Back to the project](../README.md) · [Development and releases](../CONTRIBUTING.md)

KMM follows **Fetch → Review → Publish**. Fetch stores proposals locally. Review shows what will change. Publish writes to Komga.

## The workspace

**Home** shows what needs attention: changes waiting for review, the job in progress, and each library with its series count, changes to review and last fetch. On first use it asks which libraries to manage.

**Libraries** lists series (or individual books for ebook libraries) with search, filters (changes to review, missing summary, locked fields, skipped) and sorting. Select a card to open the editor panel beside the list; use the arrows to move to the previous or next item. **Save** stores your edit in KMM, where it waits in Review. Edited fields are locked in Komga when published, unless you uncheck the option. **Fetch again from sources** asks the sources again for one series or book; **Replace my edits** is required to overwrite your manual values. **Skip when fetching** leaves a series alone in future fetches.

Each library has three tabs: **Series/Books**, **Metadata sources**, and **Settings**. Metadata sources has its own Save button for source order and options. Settings holds inclusion in automatic runs, content type, metadata rules and summary translation. Saving either tab preserves the other tab's settings. Rules and sources follow **Settings → Metadata Defaults** until you change them for that library; **Use defaults** returns to inheritance. Ebook libraries use a separate source set and match each book individually.

Under **Metadata rules → Book titles in Komga**, optionally replace displayed book titles with `Volume 1`, `Chapter 1`, the series title, or a custom template using `{series}` and `{number}`. The presets use English; use a custom template for other languages, for example `Tome {number}` or `Chapitre {number}`. Choose number padding such as `01` or `001`. Save, then fetch the library: proposed titles wait in **Review** before publishing, even when all metadata sources are disabled. This option replaces existing titles independently of the policy for other existing values, follows the library's locked-field policy, and preserves manual KMM edits unless you explicitly replace those edits. Missing metadata numbers are skipped rather than inferred from file order. Book title formatting applies to manga and webtoon libraries. Ebook titles remain unchanged. File names and embedded file metadata are never changed, and no filesystem mount is needed. Changing or disabling the option does not discard previously pending title changes; review or discard those separately.

Metadata rules choose, per field, **Leave**, **Fill in** from the sources, or **Clear**. Two policies apply to all fields: keep existing values or replace them with source values, and respect or override fields locked in Komga. Sources are tried from top to bottom; later sources fill what earlier ones missed.

**Review** groups unpublished changes into collapsible series with change counts. Series metadata is separate from compact book rows ordered by book number; title changes appear directly in each book row. Expand a book to compare all its fields before and after publication, including covers, and open long summaries to read them in full. Expand or collapse all series to scan a large batch. Discard one field or a whole series to keep Komga's value. **Publish all to Komga** or select series to publish only those. Changes Komga rejects stay in Review.

When DeepL fails, Google Translate is tried by default. Change **Use Google Translate if DeepL fails** in **Settings → External services** to disable this behavior. Exhausted quota or denied access stops further DeepL calls for that translator session; cached DeepL results remain usable. Google results use their own cache, and the original text is kept if translation still fails. Jobs already queued keep their saved settings.

**Settings** has four tabs: **Connection** (address, API key, certificate check, connection test), **Metadata Defaults** (rules and sources), **Automation** (daily fetch, new-series watcher, and whether automatic fetches wait for review or publish directly) and **External services** (Google Books and DeepL credentials, translation service, default language and whether summaries are translated by default; each library can override translation).

Back up `/config/webui.db` to preserve the local catalogue, manual edits and history.

## Setup, jobs and persistence


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

**Activity → History** records sign-ins, settings changes, edits and jobs in plain sentences. **Activity → Technical log** shows live output for troubleshooting; select any combination of **DEBUG**, **INFO**, **WARNING**, **ERROR** and **CRITICAL** (your browser remembers the selection). Each job's full log, including debug lines, is kept with the job and can be downloaded. The interface is English, with UI text centralized in `modules/webui/i18n.py`. Styles, scripts and HTMX are served locally; the browser does not need access to external CDNs. Shared interface components and interaction conventions are documented in [design-system/README.md](../design-system/README.md).

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

In **Libraries → Metadata sources**, apply a **Source template**, review its sources, then **Save**. Templates copy their settings; future template changes never modify existing library overrides. The built-in templates are **Manga**, **Webtoon**, **Ebooks — General**, and **Ebooks — French** (BnF → Open Library → Google Books). Webtoon coverage depends on the catalogues; there is no guarantee that every webtoon is listed.

Use **Add source**, remove a source, turn it off, or move it up/down with keyboard-accessible buttons. Only sources compatible with the library's saved content type are offered and queried. Previously saved incompatible choices remain stored until you explicitly save a replacement source list. An empty saved list means manual editing only. **Use defaults** restores the defaults for that content type. Under **Reuse these source settings**, save a personal template or make the current set the defaults for libraries of the same type. Explicit library overrides stay unchanged. A selected personal template can be updated or renamed with **Save library and update selected template**. Updating or deleting it does not change other libraries that used it.

Configure a shared **Google Books API key** in **Settings → External services → Google Books**. Enable the Books API in the key's Google project. The key is stored with the application settings and is never included in templates or sent to the browser as a saved value. Open Library and BnF need no key. Source requests use caches; Open Library requests are limited to one per second. API failures are reported separately from a successful empty search.

Ebooks try a validated ISBN first, then automatically search by the individual book's title and known writer when no usable ISBN match is found, including after source errors. Title matches use the source's configured minimum score, validate the author when known, and use the series language when available. Results with similar scores are left for manual selection rather than chosen by popularity. Use the **Find metadata match** action on a book to search enabled sources and pin an edition; the choice takes effect on the next fetch. Additional sources only merge metadata for a shared ISBN. A title match to another edition can supply summary, writers, cover and links; it preserves a known local ISBN and publication date unless you explicitly select that edition with Find match. Parent series and sibling books are never enriched from a selected ebook edition.

Ebook rules support book summaries, writers, covers, links, ISBN and publication dates. ISBN/date updates are opt-in; only complete valid dates are written, without inventing missing months or days. Publisher, genres, status and language remain on the parent series in Komga and are left unchanged by ebook enrichment. Existing values, locks and manual KMM edits follow the configured policies. Fetch stages changes in KMM; **Review** shows the proposed book fields and covers before **Publish** writes them to Komga. Simulation preserves metadata and saved match outcomes.

API references: [Open Library](https://openlibrary.org/developers/api), [Google Books](https://developers.google.com/books/docs/v1/using), [BnF SRU](https://api.bnf.fr/fr/api-sru-catalogue-general).


Manga libraries start with AniList, MangaDex and MangaUpdates enabled. Ebook libraries start with Open Library and Google Books (which requires an API key). Each library can select any compatible source subset, including none. Enabled providers are searched by ascending priority; when the first match lacks an enabled metadata field, the next provider fills that field without replacing higher-priority data:

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

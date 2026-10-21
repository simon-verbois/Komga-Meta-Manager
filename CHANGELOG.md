# Changelog

Release notes for Komga Meta Manager. This file and VERSION are included in the Docker image.

<!--
Add an English bullet under "## [Unreleased]" for each user-visible change, in the same commit.
Use the sections Added, Changed, Fixed, and Maintenance as needed. Do not add empty bullets.

scripts/release.sh refuses an empty Unreleased section. It creates a YYYY.W.N version using
ISO year/week and a weekly counter, dates the release heading, and reopens an empty Unreleased
section above it. VERSION and released headings are managed by that script, not edited by hand.
-->

## [Unreleased]

## [2026.43.4] — 2026-10-21

### Fixed
- Prevent GitHub Pages 404 errors when switching website languages by committing all five static language pages, supporting direct publication from `docs` as well as the Actions build, and rejecting missing or outdated generated pages before deployment.

### Maintenance
- Update GitHub repository links, the GitHub Pages address, release mirror destination and container source labels to use the renamed lowercase public repository `simon-verbois/komga-meta-manager`.

## [2026.43.3] — 2026-10-21

### Added
- Add a responsive GitHub Pages presentation site in English, French, Dutch, German and Spanish, with complete static language pages, screenshot previews, Docker setup and a prominent introduction to Inkora.
- Add reproducible desktop and mobile screenshots of the real interface using an isolated fictional catalogue, original demonstration covers and blocked external requests.
- Add an allowlisted static-site builder, local browser verification and a manually triggered GitHub Pages workflow.

### Changed
- Redesign the README around Fetch → Review → Publish, illustrated features and a concise Docker quick start; retain detailed behavior and development instructions in dedicated guides and link both the Inkora website and repository.

## [2026.43.2] — 2026-10-21

### Maintenance
- Upgrade certifi to 2026.10.19 in the application and development dependency locks to fix PYSEC-2026-4320 and restore the release security audit.

## [2026.43.1] — 2026-10-21

### Added
- Add an eight-step guided tour covering connection, library scope, metadata rules, Fetch → Review → Publish, automation and job results, with page links, keyboard navigation and a dismissible Home introduction.
- Fall back from DeepL to Google Translate by default, with an External services switch, separate caches, immediate handling of exhausted quota, and original-text preservation when both services fail.
- Centralize Google Books credentials and translation/DeepL settings in External services, preserve existing keys, and rename the default metadata tab to Metadata Defaults. Keep this page focused on configurable services.
- Show action notifications across the app as dismissible bottom-right overlays, with automatic expiry paused on hover, keyboard focus or hidden tabs; keep validation errors beside their forms.
- Content-aware metadata source sets and defaults for manga, webtoon and ebook libraries, with built-in source templates, reusable personal templates, and guided add/remove/reorder controls.
- Open Library, Google Books and BnF ebook sources, shared Google Books credentials, and conservative ISBN/title/author edition matching with manual edition selection and visible match outcomes per book.
- Book-scoped ebook enrichment for summaries, writers, covers, links, optional ISBN and full publication dates, preserving sibling books, series metadata, configured locks and manual edits through Fetch → Review → Publish.
- Remove any series (including its local books) or individual ebook from KMM with an explicit confirmation that Komga metadata, books and files remain unchanged. Discard local covers and unpublished edits, keep removed items out of the library until a future Fetch, and allow removal without a Komga connection.
- Flag locally retained series missing from Komga after a successful fetch or an explicit Check Komga, with a matching library filter. Remove a missing series and its books from KMM after confirmation and a fresh presence check; keep local edits on connection failure and never delete Komga content or files.
- Optionally use an uploaded or current series cover for every book in that series from the metadata editor. Show the book count, save covers locally for Review before publishing, and preserve drafts on failure.
- Reorder books manually with keyboard-accessible Move up/Move down controls in the numbering editor. Moving a book swaps neighboring numbers, preserves other books and prepares sort-order and configured title changes in Review; validation errors keep the edited order and values.
- Manually edit a series' book numbers from Review, including volume zero and decimal chapters, or fill consecutive numbers starting at a chosen value. Save number, sort-order and configured title changes locally for review before publishing; edited fields are locked and preserved during future fetches.
- Flag suspicious series numbering in Review before publishing, with a warning icon and expandable details for duplicate book numbers, repeated volume/chapter numbers in titles and title/number conflicts. Detection uses all locally fetched Komga books, never corrects metadata and leaves publication available.
- Optionally standardize displayed Komga book titles per library with English Volume/Chapter presets (other languages use custom templates), series titles or a custom series/number template and number padding. Fetch prepares changes in Review before publication, preserves manual KMM edits, follows the library's lock policy and never renames files.
- Manage metadata with one Fetch → Review → Publish flow. Fetching fills a persistent KMM catalogue without writing to Komga; Review lists every unpublished change per series with the value in Komga next to the value after publishing, including covers; discard a field or a series, then publish everything, one library or selected series. Rejected or locked changes stay in Review.
- Show what needs attention on Home: changes waiting for review, the job in progress, each library's series, changes to review and last fetch, an automation summary, and one next step. On first use, choose libraries and their content type, then fetch them in one step.
- Edit the local KMM metadata of a series or ebook in a side panel opened from its card, with previous/next navigation, custom values, role-specific authors and uploaded JPEG/PNG/WebP covers. Saved edits wait in Review, edited fields are locked by default, concurrent edits are detected and drafts survive failures.
- Browse libraries with search, filters (changes to review, missing summary, locked fields, skipped), sorting and status flags on every card; fetch one library, fetch one series or book again from its sources, and skip a series in future fetches.
- Set metadata rules and sources once in Settings → Defaults; every library inherits them until customized in its own settings, and can return to the defaults at any time.
- Test the Komga connection before saving and see the libraries it finds.
- Keep complete job output in SQLite, including DEBUG messages, with job details, plain-language outcomes and full log downloads that survive restarts and clearing the live view.
- Queue manual, scheduled, and watcher jobs persistently with serial execution, saved library/settings snapshots, visible outcomes and counters, cancellation, graceful stop, force stop, and running a job again.
- Discover Komga libraries automatically in the Web UI and include or exclude each library from automatic runs.
- Configure Komga, metadata rules, sources, translation, and automation through an English Web UI on port 8765.
- Create a single administrator account on first access and change its password from the Web UI.
- Start and stop the local development environment with start-kmm.sh and stop-kmm.sh.

### Changed
- Open the guided tour automatically on the first signed-in visit in each browser, remember it as soon as it opens, and move its persistent button to the top bar beside the account menu.

- Refresh job logs every second while active, follow the latest output without resetting controls, and filter levels with DEBUG hidden by default; keep every message in storage and full downloads.

- Show compact edit and red trash buttons at the bottom right of library covers on mouse hover, with accessible labels and the existing KMM-only deletion confirmation. Keep actions available for keyboard focus and touch devices; remove cover zoom, cover click actions and the button below each card.
- Replace per-book Edit order links in Review with a left-hand drag handle for reordering directly in the list, including touch dragging, keyboard arrows and move controls on click. Drops save manual number, sort-order and configured title changes in KMM for review before publication.
- Make Review easier to scan with collapsible series, separate series metadata and compact book rows ordered by book number, inline title comparisons, expandable field details and full summaries on demand.
- Give each library a dedicated Metadata sources tab between Series/Books and Settings, with independent saving, validation and reset that preserve the other library settings.
- Replace the collect/push phases, the global dry-run mode, Dry Run and Run Now with Fetch metadata and Publish. Automatic runs fetch and wait for review by default; choose "Publish to Komga automatically" in Settings → Automation to skip review. Configurations that published automatically with simulation off keep doing so.
- Reorganize navigation into Home, Libraries, Review (with the number of series waiting), Activity and Settings, with the page title in the topbar. Settings has Connection, Defaults, Automation and Translation tabs; former /config pages redirect to them.
- Choose each metadata rule per field (Leave, Fill in, Clear) with two clear policies for existing values and Komga locks, order sources with move buttons, and pick translation and source languages from lists. Each library keeps its inclusion, content type, rules, sources and translation in one form with one Save button.
- Show Activity as Jobs, History and Technical log: jobs are named Fetch, Publish or Fetch and publish with consistent status colors and plain outcomes, history entries are written as sentences, and job details explain the next step.
- Use one consistent vocabulary, sentence case and shorter help text across the interface.
- Move the username/account menu into the topbar and link the centered version to the public GitHub repository.
- Remove ASCII banners and console frames from application and job output and log the Komga client start-up at debug level; filter the technical log by DEBUG, INFO, WARNING, ERROR and CRITICAL with remembered browser selections.
- Redesign the Web UI with a calm library workspace, responsive navigation, guided settings, and accessible shared components.
- Warn about unsaved edits and provide clear loading, empty, error, and save feedback, keeping entries after validation errors.
- Store configuration in SQLite and reload it without restarting the container; import existing YAML configuration on first startup.
- Keep the Web UI available when scheduling is disabled or watcher initialization fails.

### Fixed
- Automatically fall back from unavailable or unmatched ebook ISBNs to scored title/author matching, honor each source's confidence threshold, leave ambiguous results for manual selection, and preserve known ISBN/date values when a different edition is matched by title.
- Pause uncached Google Books requests for 60 seconds after server failures while continuing other enabled ebook sources, use the series language for edition matching, and distinguish source outages from missing editions in fetch logs.
- Distinguish Google Books service outages, rejected credentials, access restrictions, quota limits and connection failures after retries; avoid language filters for exact ISBN lookups.

- Detect numbering warnings in titles whose volume/chapter label is followed by parenthesized or bracketed release information, including volume-zero offsets.
- Allow explicitly saved manual edits to update known locked Komga fields while keeping them locked; publication still blocks locked values or locks changed in Komga since the last fetch.

- Keep manual metadata editing and custom covers available for libraries that are not included in automatic runs.
- Preserve included libraries when saving Komga connection settings, preserve the DeepL API key when switching translation engines, and use library-specific exclusions when the watcher queues new series.
- Request book covers as images so Komga serves thumbnails correctly in the library browser.
- Report rejected series metadata or book-author writes as job failures and record why locked or existing fields are preserved.
- Render technical log lines as compact rows with separate timestamps, severity and wrapped messages, preserving traceback indentation without overflowing the page.
- Stop labeling fetch jobs as live updates, show the same status colors on every screen, pluralize counts ("1 book"), and remove the misleading Retry button that only reloaded the job page.

### Maintenance

- Exclude the local metadata database lock file from Git.
- Serve interface styles, scripts, and HTMX from the application so the UI no longer depends on external CDNs.
- Document mandatory changelog updates and development container rebuilds in AGENTS.md.
- Document in AGENTS.md that project content, reports and screenshots stay local and are never published to cloud services.
- Define the product vision and GUI/UX guidelines for simple metadata management across manga, webtoon, and ebook libraries in AGENTS.md.
- Prepare interface text for future translations and add Web UI regression coverage, including Review, discarding, publishing, library inheritance and targeted fetches.
- Document the Fetch → Review → Publish interaction rules, layout and editor conventions in design-system/README.md and the README.
- Automate versioned changelog releases and package version, release notes, and the MIT license in Docker builds.

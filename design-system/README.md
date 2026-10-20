# KMM interface

KMM uses a quiet library workspace: warm neutral surfaces, forest green actions,
clear typography and a persistent task-based navigation. The design follows the
minimal dashboard guidance from UI/UX Pro Max, adapted to a personal library tool.
Marketing layouts from the skill's search results are not used in application screens.

## Shared implementation

- `modules/webui/static/app.css` owns color tokens, spacing and responsive components.
- `modules/webui/templates/macros/ui.html` owns icons, labeled fields, checkbox rows,
  page headings and save controls. Prefer these components on new screens.
- `modules/webui/static/app.js` owns navigation, password visibility, unsaved edit
  feedback, request feedback, run controls and local timestamps.
- Interface copy belongs in `modules/webui/i18n.py` and remains English.
- CSS, JavaScript and HTMX are served locally; there is no frontend build step,
  external font dependency or runtime CSS compiler. The vendored HTMX 2.0.4 license
  is stored next to its script.

## Interaction rules

KMM follows one model everywhere: **Fetch** fills the local KMM catalogue and never
writes to Komga, **Review** shows each unpublished change as "In Komga now" next to
"After publishing", and **Publish** is the only action that writes to Komga. Do not
reintroduce phases, a global dry-run switch or preview modes in the interface; the
Review page is the preview. Use these verbs consistently: Fetch, Review, Publish,
Discard, Save. "Included" means a library takes part in automatic runs and Fetch
metadata on Home.

Saving settings never starts a job. Every form uses one Save button and shows unsaved
changes in its save bar; do not mix immediate saves and Save buttons on one screen.
Confirm only actions that write to Komga or discard work. Keep entries after
validation errors.

Per-library rules and sources inherit Settings → Defaults until changed; show
"Uses defaults" or a "Use defaults" reset. Metadata rules are a segmented choice
per field (Leave, Fill in, Clear) plus two policies (existing values, Komga locks).
Sources are an ordered list with move buttons. Prefer selects for languages.

Status colors are shared: success for Done, danger for Failed, blue with a pulsing
dot for Running, warning for changes to review, neutral otherwise.

Navigation collapses into an inline menu below 768 px. Use native controls, visible
labels and keyboard focus, a skip link, reduced motion and explicit feedback for
loading, empty lists, success and failure. Keep horizontal overflow inside tables.

## Layout

The topbar holds the visible page title (`{% block heading %}`) and the account
menu; detail pages add a back link. Navigation: Home, Libraries, Review (with the
number of series waiting), Activity, Settings. Home leads with one next step
(review, fetch, or choose libraries), then the job in progress, the library table
and an automation summary. Activity has Jobs, History and Technical log tabs.

Libraries uses library pills (with pending counts), a header with the Fetch action,
and two tabs: the series or book grid, and a single settings form. Cards are
buttons that open the editor drawer; flags show changes to review, skipped series,
missing summaries and locks. Manga and webtoon libraries list series; ebook
libraries list books.

## Editor drawer

The drawer edits the local KMM copy and saves directly; the change then waits in
Review. Previous/next buttons follow the visible, filtered order. Series and ebook
fields have distinct scopes. Author role replacements are opt-in; mixed values are
never collapsed implicitly. Edited fields are locked by default. Uploaded covers
are validated before any writes. "Fetch again from sources" and "Skip when
fetching" live below the form; replacing manual edits requires an explicit choice.

## Verification

Run the Python suite and Ruff, rebuild with `./start-kmm.sh`, check `/health`, then
verify the UI in Chromium at desktop and mobile sizes. Use an isolated application
and fake Komga responses to test mutations without changing actual library metadata.

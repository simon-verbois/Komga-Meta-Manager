# Website and demonstration screenshots

The presentation site is a separate static artifact. It has no dependency on the
running KMM application, package manager, external fonts, analytics or CDNs. Links
and all translated content work without JavaScript. Optional JavaScript adds a
screenshot dialog, keyboard-accessible gallery tabs and a Compose copy button.

## Structure

- `docs/site-template.html`: English source, page structure and accessible image descriptions.
- `docs/index.html`, `docs/{fr,nl,de,es}/index.html`: generated, committed static language pages.
- `docs/styles.css`, `docs/site.js`, `docs/favicon.svg`: local website resources.
- `docs/locales/{fr,nl,de,es}.json`: complete website translations, keyed by English source copy.
- `docs/screenshots/`: nine real-interface captures with entirely fictional content.
- `docs/images/inkora-home.png`: Inkora's existing fictional demonstration capture,
  copied from its presentation assets to keep this site self-contained.
- `scripts/build_site.py`: standard-library-only assembly, localization and offline link validation.
- `scripts/capture_screenshots.py`: isolated KMM demonstration data and screenshot capture.
- `scripts/check_site_browser.py`: local Chromium verification and visual evidence.
- `.github/workflows/pages.yml`: manual, default-branch GitHub Pages deployment.

Like Inkora, the site commits every language page so publishing `docs` directly
also works. The builder checks that those pages match the template and translations,
then copies only explicitly listed public website resources. User guides,
translation source catalogues, application code, databases and configuration files
are not included in the website artifact. It refuses nonempty output directories.

## Local preview

From the repository root, with Python 3.11 or later:

```bash
python3 scripts/build_site.py
python3 -m http.server 4173 --bind 127.0.0.1 --directory build
```

Open **http://127.0.0.1:4173/site/**. For another build, choose a fresh destination,
for example `python3 scripts/build_site.py --output build/site-review-2`. Do not
edit the generated output or the committed language pages directly.

The generated site contains:

| URL relative to the website | Language |
| --- | --- |
| `/` | English |
| `/fr/` | French |
| `/nl/` | Dutch |
| `/de/` | German |
| `/es/` | Spanish |

The visible language menu uses native names, marks the current language and links
directly to static pages. There are no browser-language redirects. Each page has
its own HTML language, translated title, description, content, image descriptions
and navigation labels, with alternate-language links. Assets use relative paths,
including under a GitHub project prefix. KMM itself remains English; screenshot
captions make this explicit in the translated pages.

## Translation maintenance

Edit English copy in `docs/site-template.html`, then update the corresponding keys
in all four JSON catalogues in the same change. Regenerate and check the committed
pages before committing them:

```bash
python3 scripts/build_site.py --generate
python3 scripts/build_site.py --check
```

Missing translations fail generation before any page is written. Missing or
outdated pages fail the build before it creates an artifact. Preserve brand names,
URLs and installation code.
Copy-button feedback is localized in `docs/site.js`; keep all five variants in sync.
Review each language in the browser, including longer French/German headings and
the narrow-screen navigation. The English README links to the English user guide.

## Screenshots

The captures render **the production application routes, templates, CSS and JS**,
using a temporary database and invented titles, creators and publishers. Original
geometric SVG artwork supplies the covers. No Komga account, real library,
configuration file or external catalogue is used. A strict fake HTTP responder
serves only demonstration thumbnails, workers cannot start, and browser requests
are restricted to the loopback instance. The script does not launch `modules.main`
or import legacy configuration.

Install optional browser tooling in a local virtual environment. It is separate
from application/runtime dependencies:

```bash
python3 -m venv .tooling/site-qa
.tooling/site-qa/bin/pip install --require-hashes -r requirements-dev.txt
.tooling/site-qa/bin/pip install playwright==1.64.0
.tooling/site-qa/bin/python -m playwright install chromium
.tooling/site-qa/bin/python -m scripts.capture_screenshots
```

This intentionally refreshes the nine demonstration PNG files. Desktop captures
use a 1440-pixel viewport at 1.5× resolution (the library overview uses a shorter
820-pixel frame); mobile captures use 390×844 at 1.5×. The application version in
the screenshot footer comes from `VERSION`. Capture dates/results are fictional
fixture data. Review images for clipping, loading states, cover quality and any
accidental personal information before committing them.

Inkora's screenshot is a host-rendered Flutter demonstration capture with fictional
content. It is an illustration of the separate reader project, not a KMM feature.
The Inkora website and repository are linked prominently; KMM requires neither.

## Checks

After building into a fresh output directory:

```bash
.tooling/site-qa/bin/python -m scripts.check_site_browser
.tooling/site-qa/bin/python -m scripts.check_site_browser --site docs --output artifacts/site-qa-docs
python -m pytest tests/test_site.py
ruff check scripts/build_site.py scripts/capture_screenshots.py scripts/check_site_browser.py tests/test_site.py
```

Browser checks cover all five languages at 360, 390, 768, 1024 and 1440 pixels,
local image loading, horizontal overflow, enlarged text, tab keyboard navigation,
screenshot dialog dismissal and focus restoration, clipboard success/failure,
native FAQ/language controls, and every pair of language links on mobile and
desktop, plus all language pairs without JavaScript. Run them against both the
artifact and committed `docs` to cover both publication modes under a project prefix.
Any external browser request fails verification. Reports and full-page website
captures stay in ignored `artifacts/site-qa/`; they are not public-site assets.
These checks supplement visual inspection, not exhaustive assistive-technology QA.

## GitHub Pages

In the **public GitHub repository**, choose **Settings → Pages → Source → GitHub
Actions**. Then manually run **KMM presentation site** on the default branch. The
workflow builds `build/site`, uploads only that artifact and deploys through the
`github-pages` environment. It has no push trigger and changes no release/version
behavior. Preparation and local verification do not publish anything.

Expected project URL after publication:
`https://simon-verbois.github.io/komga-meta-manager/`.

Direct branch publication also works: choose **Deploy from a branch**, the default
branch and **/docs**. All five language pages are committed there, with relative
links that preserve the GitHub project prefix. Regenerate them whenever the
template or translations change. The Actions artifact remains the recommended
option because it excludes source templates, catalogues and user guides, and
checks generated pages before deployment.

No GitHub Pages setting or remote content is changed by the local scripts. See
GitHub's official [custom workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

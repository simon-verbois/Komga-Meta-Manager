# KMM Web UI — TODO

## Architecture decisions
- Port `8765`
- **No more `config.yml`** — all config stored in SQLite (`/config/webui.db`) via the Web UI
- Hot config reload (no container restart needed)
- Single user (first-run setup wizard creates the account)
- Stack: **FastAPI + Jinja2 + HTMX + TailwindCSS CDN**
- Two log viewers: **Audit log** (DB-backed) + **Execution log** (in-memory circular buffer)

---

## Phase 1 — Infrastructure

### Dependencies
- [x] Add to `requirements.in`: `fastapi`, `uvicorn[standard]`, `python-multipart`, `bcrypt`, `itsdangerous`
- [x] Recompile `requirements.txt` and `requirements-dev.txt`

### Web UI core (`modules/webui/`)
- [x] `__init__.py`
- [x] `db.py` — SQLite helpers (users, settings/config, audit_log tables)
- [x] `auth.py` — bcrypt password check, signed cookie session (itsdangerous)
- [x] `config_store.py` — read/write AppConfig JSON in DB, hot reload logic
- [x] `log_buffer.py` — custom logging.Handler + deque circular buffer (execution log)
- [x] `i18n.py` — translation dict system, EN only, extensible
- [x] `app.py` — FastAPI app factory, Jinja2, middleware, route registration

### Routes
- [x] `routes/__init__.py`
- [x] `routes/guards.py` — session authentication and redirect helpers
- [x] `routes/setup.py` — first-run wizard (create account + initial Komga config)
- [x] `routes/auth_routes.py` — GET/POST login, POST logout, GET/POST account (password change)
- [x] `routes/dashboard.py` — dashboard, Run Now, Dry-Run toggle, scheduler controls
- [x] `routes/config_routes.py` — all config section GET/POST pages
- [x] `routes/logs.py` — audit log viewer + execution log viewer (HTMX polling)

### Templates (`modules/webui/templates/`)
- [x] `base.html` — layout, nav, TailwindCSS CDN, HTMX CDN
- [x] `setup.html` — first-run wizard
- [x] `login.html`
- [x] `account.html` — password change
- [x] `dashboard.html` — status cards, Run Now btn, Dry-Run toggle, scheduler form
- [x] `logs.html` — two tabs: Audit / Execution (with Debug toggle)
- [x] `config/system.html`
- [x] `config/komga.html`
- [x] `config/providers.html`
- [x] `config/processing.html`
- [x] `config/translation.html`
- [x] `partials/exec_log_lines.html` — HTMX fragment for log polling
- [x] `partials/audit_log_lines.html` — HTMX fragment
- [x] `partials/dry_run_badge.html` — HTMX fragment
- [x] `partials/job_status.html` — HTMX fragment
- [x] `partials/config_nav.html` — sub-navigation fragment
- [x] `partials/config_alerts.html` — success and error messages fragment

### Integrate into `main.py`
- [x] Load config from SQLite / fallback to initial Web UI setup
- [x] Auto-migrate legacy `config.yml` into database if found
- [x] Start uvicorn in a daemon thread before the main loop
- [x] Pass shared `AppConfig` ref + reload callback + job trigger event to web app
- [x] Handle "no config yet" state (run in setup-only mode until wizard is done)
- [x] Retain compatibility with `initialize_application` and `run_once_mode` for tests

### Docker / Compose
- [x] `Dockerfile` — `EXPOSE 8765`
- [x] `compose.yml` — add `ports: ["8765:8765"]`
- [x] `compose-testing.yml` — add `ports: ["8765:8765"]`

---

## Phase 2 — Configuration pages

- [x] System page: dry_run, debug, scheduler (enabled, run_at), watcher (enabled, polling_interval_minutes)
- [x] Komga page: url, api_key (masked with show/hide), libraries (textarea list), verify_ssl
- [x] Providers page: per-provider priority, min_score, allow_adult, preferred_language, cache.ttl_hours
- [x] Processing page: overwrite_existing, force_unlock, exclude_series, update_fields.*, remove_fields.*
- [x] Translation page: enabled, provider, target_language, deepl.api_key (masked with show/hide)
- [x] Validation via existing Pydantic models on save
- [x] Hot reload: update in-memory AppConfig + restart scheduler if needed
- [x] Audit log entry on every save

---

## Phase 3 — Dashboard & controls

- [x] Status cards: scheduler (enabled/next run), watcher (enabled/interval), dry-run state
- [x] **Dry-Run toggle** — prominent warning badge when disabled (writes WILL happen)
- [x] **Run Now** button — triggers job in background thread, shows running indicator
- [x] Job status: idle / running / last result (success/failure + timestamp)
- [x] Scheduler form inline on dashboard (enable/disable + run_at time)

---

## Phase 4 — Log viewers

- [x] **Execution log** — circular buffer (500 lines), HTMX polling every 3s, Debug toggle (filters DEBUG lines server-side)
- [x] **Audit log** — SQLite-backed, paginated, shows: timestamp / action / detail
- [x] Audit entries auto-created for: config saved, run triggered, dry-run toggled, login, setup completed
- [x] Clear execution log button

---

## Phase 5 — Polish

- [x] i18n structure validated (all UI strings go through `t()`)
- [x] Error handling: flash messages on form errors
- [x] Password change page (`/account`)
- [x] Responsive layout check
- [x] Update README (remove config.yml references, add Web UI section)
- [x] Update `config/config.yml.template` (keep for reference/migration note)
- [x] k8s manifest: add 05-service.yaml, update PVC and deployment mounts for unified /config storage
- [x] Unit tests for Web UI backend (`tests/test_webui.py`)
- [x] HTTP route integration tests (`tests/test_webui_routes.py`)

---

## Phase 6 — Verification & Quality Gates

- [x] **Full Pytest Suite**: 135 tests passed under Python 3.13 after release integration; coverage 71.32% (required minimum: 60%). The Web UI suite was also verified under Docker Python 3.11 before release integration.
- [x] **Linter**: `ruff check modules tests` passed with 0 errors.
- [x] **Compose validation**: `compose.yml` and `compose-testing.yml` syntax and port mappings validated.
- [x] **Hot reload**: Verified in-memory config refresh and continuous loop listener.
- [x] **Database & Migration**: SQLite database storage verified in `/config/webui.db` with legacy `config.yml` auto-migration.

## Final review — runtime regressions

- [x] Keep idle Web UI running without executing jobs on startup or config saves.
- [x] Remove test-only runtime branches; exercise shutdown explicitly in tests.
- [x] Add a dedicated Dry Run action using a configuration snapshot.
- [x] Serialize manual, scheduled, and watcher processing.
- [x] Fix optional translation page, numeric validation, Debug polling, and duplicate status IDs.
- [x] Prevent duplicate log handlers during hot reload and apply logging level changes.
- [x] Keep setup reachable through Kubernetes probes and read-only image filesystems.
- [x] Enforce one account in SQLite, reject cross-origin mutations, and invalidate sessions on password changes.
- [x] Regression tests and container verification.
- [x] Docker build with hash-verified dependencies; runtime verified with a read-only root filesystem.
- [x] Chromium walkthrough: setup, all five config pages, dashboard, Debug polling, and audit viewer; no JavaScript errors.
- [x] Desktop (1280px) and mobile (390px) layout verified; no horizontal overflow.
- [x] Restart preserves account, configuration, and audit history; setup remains closed.

### Validation scope
- HTTP integration tests use mocked processing; no metadata writes were performed against a real Komga server.
- Browser assets currently load from public Tailwind and HTMX CDNs.
- Remaining warnings are dependency deprecations from Starlette's HTTPX test client and existing cookie test calls.

## Release workflow (Agon conventions)

- [x] Inspect Agon's release script and Forgejo build in `../ascend`.
- [x] Retain `VERSION` and MIT `LICENSE`; add English `CHANGELOG.md` with Unreleased notes.
- [x] Automate ISO year/week/counter versions, dated release notes, commit, annotated tag, and atomic push.
- [x] Require clean `main` and nonempty notes before release.
- [x] Check tag/version/changelog consistency in CI; publish the version tag and `latest`.
- [x] Package version, changelog, and license with OCI metadata; show the installed version in the Web UI.
- [x] Ignore the development database and document the release procedure.
- [x] Validate releases against temporary Git remotes, full tests (135 passed), and the packaged Docker metadata.
- [x] Verify packaged VERSION, CHANGELOG.md, MIT LICENSE, and application version inside the Python 3.11 image.
- [x] No project release, tag, commit, or remote publication triggered during implementation.


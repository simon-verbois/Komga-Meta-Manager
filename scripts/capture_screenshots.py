#!/usr/bin/env python3
"""Capture the real KMM interface against an isolated, entirely fictional catalogue.

Run from the repository root with application dependencies and Playwright installed:
    python -m scripts.capture_screenshots

No user configuration is read. The database is temporary, workers cannot start,
and every outbound requests call is replaced by a strict fixture responder.
"""

import argparse
from contextlib import contextmanager
import html
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import requests
import uvicorn

from modules.config import AppConfig
from modules.job_queue import JobQueue
from modules.local_metadata import LocalCatalogue
from modules.models import KomgaBook, KomgaSeries
from modules.webui import auth, config_store, db
from modules.webui.app import create_app

ROOT = Path(__file__).resolve().parents[1]
SERVER = "http://demo.komga.invalid"
LIBRARIES = (("manga", "Manga"), ("webtoon", "Webtoons"), ("ebook", "Ebooks"))
# Original fictional titles, creators and geometric cover artwork.
TITLES = (
    ("Aster & the Sea", "Mira Sato", "#163e42", "#f2c16e"),
    ("The Glass Orchard", "Noa Mori", "#d7d7b4", "#294d3b"),
    ("Letters from the Moon", "Emi Arai", "#272943", "#e2b7a5"),
    ("Paper Cities", "Ren Ito", "#dca66d", "#49352f"),
    ("Quiet Satellites", "Hana Kado", "#274658", "#cae0d9"),
    ("The Last Botanist", "Akira Noma", "#596b43", "#f1ddab"),
    ("Under an Amber Sky", "Yui Kawa", "#a65035", "#f6d9a2"),
    ("Wildflower Station", "Sora Nishi", "#e5c9bb", "#724361"),
    ("A Map of Small Things", "Jules Arden", "#e7d9b8", "#426359"),
    ("The Night Archivist", "Alex Rowan", "#29394f", "#e8b56b"),
    ("Where Rivers Begin", "Robin Vale", "#4d6b70", "#e4e0bf"),
    ("An Atlas of Rain", "Charlie Reed", "#706d85", "#e6d8c0"),
)


class ScreenshotQueue(JobQueue):
    """Expose actual job history while making worker execution impossible."""

    def start(self) -> None:
        pass

    def enqueue(self, *args, **kwargs) -> int:
        raise RuntimeError("Screenshot fixtures cannot execute jobs")


def cover_svg(index: int) -> bytes:
    """Draw original vector artwork; no copyrighted covers or remote assets."""
    title, creator, background, foreground = TITLES[index % len(TITLES)]
    words = title.split()
    midpoint = (len(words) + 1) // 2
    lines = (" ".join(words[:midpoint]), " ".join(words[midpoint:]))
    art = (
        '<circle cx="160" cy="223" r="93" fill="none" stroke-width="2"/>'
        '<circle cx="160" cy="223" r="68" fill="none" stroke-width="1"/>'
        '<path d="M20 350 120 170 215 350ZM110 350 224 225 310 350Z" stroke="none"/>'
        '<circle cx="220" cy="145" r="24" stroke="none"/>'
        if index % 3 == 0
        else '<path d="M75 335V200a85 85 0 0 1 170 0v135M105 335V205a55 55 0 0 1 110 0v130" '
        'fill="none" stroke-width="14"/>'
        '<circle cx="160" cy="258" r="29" stroke="none"/>'
        if index % 3 == 1
        else '<circle cx="160" cy="235" r="96" stroke="none"/>'
        f'<circle cx="195" cy="206" r="78" fill="{background}" stroke="none"/>'
        '<path d="M45 330h230M60 345h200M85 360h150" fill="none" stroke-width="2"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="450" viewBox="0 0 320 450">'
        f'<rect width="320" height="450" fill="{background}"/>'
        f'<rect x="14" y="14" width="292" height="422" rx="1" fill="none" stroke="{foreground}" opacity=".4"/>'
        f'<g fill="{foreground}" stroke="{foreground}" opacity=".85">{art}</g>'
        f'<g fill="{foreground}" text-anchor="middle" font-family="Georgia,serif">'
        f'<text x="160" y="52" font-size="12" letter-spacing="4">A KMM DEMO EDITION</text>'
        f'<text x="160" y="90" font-size="25">{html.escape(lines[0])}</text>'
        f'<text x="160" y="119" font-size="25">{html.escape(lines[1])}</text>'
        f'<text x="160" y="406" font-size="15" letter-spacing="2">{html.escape(creator.upper())}</text>'
        "</g></svg>"
    ).encode()


def fixture_response(method: str, url: str, **kwargs) -> requests.Response:
    """Serve only fictional Komga thumbnails; reject all other outbound calls."""
    parsed = urlsplit(url)
    if method.upper() != "GET" or parsed.netloc != "demo.komga.invalid" or not parsed.path.endswith("/thumbnail"):
        raise AssertionError(f"Unexpected outbound request blocked: {method} {parsed.netloc}")
    identifier = parsed.path.split("/")[-2]
    index = int(identifier.split("-")[-1])
    response = requests.Response()
    response.status_code = 200
    response.headers["content-type"] = "image/svg+xml"
    response._content = cover_svg(index)
    return response


def seed_catalogue(database: Path) -> None:
    """Populate a fresh database without consulting the local /config directory."""
    db.init_db(database)
    auth._serializer = None
    config_store._config = None
    config_store._reload_callback = None
    db.create_user("demo", auth.hash_password("FictionalScreenshotAccount!"))
    cfg = AppConfig.model_validate(
        {
            "komga": {"url": SERVER, "api_key": "fictional-demo-key", "libraries": [name for _, name in LIBRARIES]},
            "library_settings": {key: {"name": name, "content_type": key} for key, name in LIBRARIES},
            "system": {
                "workflow": "collect",
                "dry_run": False,
                "auto_publish": False,
                "scheduler": {"enabled": True, "run_at": "03:00"},
                "watcher": {"enabled": True, "polling_interval_minutes": 15},
            },
        }
    )
    config_store.save_config_to_db(cfg.model_dump(mode="json"))
    store = LocalCatalogue(SERVER)
    with db.get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS local_libraries (server TEXT, id TEXT, name TEXT, PRIMARY KEY(server, id))"
        )
        conn.executemany(
            "INSERT INTO local_libraries VALUES (?, ?, ?)", [(SERVER, key, name) for key, name in LIBRARIES]
        )
    for library_id, _ in LIBRARIES:
        indexes = range(7) if library_id == "manga" else range(8, 12) if library_id == "ebook" else range(4)
        for index in indexes:
            title, creator, *_ = TITLES[index]
            series_id = f"{library_id}-{index}"
            metadata = {
                "title": title,
                "summary": "",
                "status": "ONGOING",
                "publisher": "",
                "language": "en",
                "genres": [],
                "tags": [],
                "links": [],
            }
            metadata.update(
                {
                    f"{field}Lock": False
                    for field in (
                        "status",
                        "title",
                        "summary",
                        "readingDirection",
                        "publisher",
                        "ageRating",
                        "language",
                        "genres",
                        "tags",
                        "links",
                        "totalBookCount",
                    )
                }
            )
            count = 1 if library_id == "ebook" else 4 + index % 4
            series = KomgaSeries.model_validate(
                {
                    "id": series_id,
                    "libraryId": library_id,
                    "name": title,
                    "booksCount": count,
                    "metadata": metadata,
                }
            )
            store.import_item("series", series, library_id, series_id)
            summary = (
                f"When a forgotten letter arrives at the harbour, {title.split()[0]} sets out to find its author. "
                "A quiet journey through distant islands, unexpected friendships and the stories we leave behind."
            )
            if library_id == "manga" and index < 3:
                store.patch(
                    "series",
                    series_id,
                    {"summary": summary, "genres": ["Adventure", "Slice of Life"], "publisher": "Northlight Press"},
                )
            elif library_id != "ebook":
                # These entries already have metadata in the fictional Komga snapshot.
                series.metadata.summary = summary
                series.metadata.publisher = "Northlight Press"
                store.import_item("series", series, library_id, series_id)
            for number in range(1, count + 1):
                book = KomgaBook.model_validate(
                    {
                        "id": f"{library_id}-book-{number}-{index}",
                        "seriesId": series_id,
                        "name": title if library_id == "ebook" else f"{title} — {number:02}",
                        "number": number,
                        "metadata": {
                            "title": title if library_id == "ebook" else f"Volume {number}",
                            "titleLock": False,
                            "summary": "",
                            "summaryLock": False,
                            "number": str(number),
                            "numberLock": False,
                            "numberSort": number,
                            "numberSortLock": False,
                            "tagsLock": False,
                            "releaseDateLock": False,
                            "authors": [{"name": creator, "role": "writer"}],
                            "authorsLock": False,
                        },
                    }
                )
                store.import_item("books", book, library_id, series_id)
                if library_id == "ebook" and index < 10:
                    store.patch("books", book.id, {"summary": summary})
    # Completed demo jobs are display data; the queue can never launch workers.
    with db.get_db() as conn:
        for index, (action, source, processed) in enumerate(
            (
                ("collect", "scheduler", 15),
                ("push", "manual", 7),
                ("collect", "watcher", 2),
                ("collect", "manual", 7),
            )
        ):
            saved = cfg.model_dump(mode="json")
            saved["system"].update(workflow=action, dry_run=False)
            conn.execute(
                "INSERT INTO jobs (source, status, config, series_ids, book_ids, created_at, started_at, finished_at, processed) "
                "VALUES (?, 'succeeded', ?, 'null', 'null', ?, ?, ?, ?)",
                (
                    source,
                    json.dumps(saved),
                    f"2026-10-20T0{index + 3}:00:00+00:00",
                    f"2026-10-20T0{index + 3}:00:00+00:00",
                    f"2026-10-20T0{index + 3}:00:32+00:00",
                    processed,
                ),
            )


@contextmanager
def demo_server(port: int):
    """Run the production routes on loopback, with temporary data and no workers."""
    with tempfile.TemporaryDirectory(prefix="kmm-screenshots-") as directory:
        seed_catalogue(Path(directory) / "webui.db")
        server = uvicorn.Server(
            uvicorn.Config(create_app(job_queue=ScreenshotQueue()), host="127.0.0.1", port=port, log_level="error")
        )
        with patch("requests.sessions.Session.request", side_effect=fixture_response):
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("Screenshot server did not start")
                    time.sleep(0.05)
                yield f"http://127.0.0.1:{port}"
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError("Screenshot server did not stop")


def capture(output: Path, port: int) -> None:
    """Render desktop/mobile captures and assert local-only, error-free browsing."""
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    with demo_server(port) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=1.5,
            locale="en-GB",
            timezone_id="UTC",
            reduced_motion="reduce",
        )
        context.add_cookies(
            [{"name": auth.SESSION_COOKIE, "value": auth.create_session_token("demo"), "url": base_url}]
        )
        context.add_init_script('localStorage.setItem("kmm-guided-tour-v1", "seen")')

        def local_only(route):
            if not route.request.url.startswith(base_url + "/"):
                errors.append("Unexpected nonlocal browser request")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                errors.append(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None
            ),
        )

        def screenshot(name: str, path: str, ready: str = "main") -> None:
            page.goto(base_url + path)
            expect(page.locator(ready).first).to_be_visible()
            page.evaluate("document.fonts.ready")
            page.wait_for_function("""Array.from(document.querySelectorAll('img[src]')).filter(i =>
                i.getBoundingClientRect().width > 0 && i.getBoundingClientRect().top < innerHeight
            ).every(i => i.complete && i.naturalWidth > 0)""")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
            page.screenshot(path=str(output / f"{name}.png"), animations="disabled")
            print(f"Captured {name}")

        screenshot("home", "/")
        page.set_viewport_size({"width": 1440, "height": 820})
        screenshot("libraries", "/libraries?library=manga", ".book-card")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator('[data-overwrite][data-series-id="manga-0"]').focus()
        page.keyboard.press("Enter")
        expect(page.locator("#overwrite-dialog")).to_be_visible()
        expect(page.locator("#manual-title")).to_have_value("Aster & the Sea")
        page.screenshot(path=str(output / "editor.png"), animations="disabled")
        screenshot("review", "/review?library=manga", ".review-group")
        page.locator(".review-series-details").first.locator("summary").first.click()
        page.screenshot(path=str(output / "review.png"), animations="disabled")
        screenshot("sources", "/libraries?library=manga&tab=sources", "#source-template")
        screenshot("ebooks", "/libraries?library=ebook", ".book-card")
        screenshot("activity", "/logs", ".job-row")
        page.set_viewport_size({"width": 390, "height": 844})
        screenshot("mobile-home", "/")
        screenshot("mobile-review", "/review?library=manga", ".review-group")
        page.locator(".review-series-details").first.locator("summary").first.click()
        page.screenshot(path=str(output / "mobile-review.png"), animations="disabled")
        browser.close()
    if errors:
        raise AssertionError(errors)
    print(
        "Captures verified: fictional catalogue, temporary database, no external browser requests, no HTTP/JS errors."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/screenshots")
    parser.add_argument("--port", type=int, default=8879)
    args = parser.parse_args()
    capture(args.output, args.port)

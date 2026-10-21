#!/usr/bin/env python3
"""Verify the built site in local Chromium without any external browser requests."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright

from scripts.build_site import LANGUAGES, ROOT, validate_site


class QuietHandler(SimpleHTTPRequestHandler):
    """Keep local asset request logs out of the verification output."""

    def log_message(self, *args):
        pass


def verify(site: Path, output: Path) -> None:
    """Check all languages, responsive layouts, keyboard use and JS-free fallbacks."""
    site = site.resolve()
    validate_site(site)
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site.parent)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    base = f"{origin}/{site.name}/"
    errors, reports = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(reduced_motion="reduce", permissions=["clipboard-read", "clipboard-write"])

            def local_only(route):
                if not route.request.url.startswith(origin + "/"):
                    errors.append("Unexpected external browser request")
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
            for language, label in LANGUAGES.items():
                url = base if language == "en" else base + language + "/"
                for width in (360, 390, 768, 1024, 1440):
                    page.set_viewport_size({"width": width, "height": 960 if width >= 768 else 844})
                    response = page.goto(url)
                    assert response.status == 200
                    expect(page.locator("html")).to_have_attribute("lang", language)
                    expect(page.locator("[data-current-language]")).to_have_text(label)
                    expect(page.locator("h1")).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (language, width)
                    for image in page.locator("img[src]:visible").all():
                        image.scroll_into_view_if_needed()
                        expect(image).to_have_js_property("complete", True)
                        assert image.evaluate("i => i.naturalWidth > 0"), image.get_attribute("src")
                    page.evaluate("scrollTo(0, 0)")
                    if width in (390, 1440):
                        page.screenshot(
                            path=str(output / f"{language}-{width}.png"), full_page=True, animations="disabled"
                        )
                        # Exercise every language link under a project prefix on mobile and desktop.
                        for target in LANGUAGES:
                            picker = page.locator(".language-picker")
                            picker.locator("summary").click()
                            picker.locator(f'a[hreflang="{target}"]').click()
                            expected_url = base if target == "en" else base + target + "/"
                            expect(page).to_have_url(expected_url)
                            expect(page.locator("html")).to_have_attribute("lang", target)
                            expect(page.locator(".language-picker [aria-current=page]")).to_have_attribute(
                                "hreflang", target
                            )
                            assert page.goto(url).status == 200
                    reports.append({"language": language, "width": width, "layout": "pass", "images": "pass"})

                tabs = page.get_by_role("tab")
                tabs.nth(1).click()
                expect(page.locator("#panel-editor")).to_be_visible()
                page.keyboard.press("End")
                expect(tabs.last).to_be_focused()
                expect(page.locator("#panel-activity")).to_be_visible()
                page.keyboard.press("Home")
                expect(tabs.first).to_be_focused()
                expect(page.get_by_role("tabpanel").filter(visible=True)).to_have_count(1)

                link = page.locator(".hero-figure [data-preview]")
                link.click()
                expect(page.locator("#preview")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#preview")).not_to_be_visible()
                expect(link).to_be_focused()
                link.click()
                page.locator(".close-preview").click()
                expect(link).to_be_focused()
                page.locator(".copy-button").click()
                expect(page.locator(".copy-status")).not_to_be_empty()
                clipboard = page.evaluate("navigator.clipboard.readText()")
                assert "./config:/config" in clipboard
                page.evaluate("""Object.defineProperty(navigator, 'clipboard', {configurable: true,
                    value: {writeText: () => Promise.reject(new Error('Unavailable'))}})""")
                page.locator(".copy-button").click()
                failure = page.locator(".copy-status").inner_text()
                assert failure and "copied." not in failure.lower()
                first_faq = page.locator(".faq details").first
                first_faq.locator("summary").click()
                expect(first_faq).to_have_attribute("open", "")

                picker = page.locator(".language-picker")
                picker.locator("summary").click()
                page.keyboard.press("Escape")
                expect(picker).not_to_have_attribute("open", "")
                expect(picker.locator("summary")).to_be_focused()

                # User-enlarged text, including the longer translated headings.
                page.set_viewport_size({"width": 390, "height": 844})
                page.evaluate("""() => {
                    const sizes = Array.from(document.querySelectorAll('body *'))
                        .filter(element => !(element instanceof SVGElement))
                        .map(element => [element, parseFloat(getComputedStyle(element).fontSize) * 2]);
                    sizes.forEach(([element, size]) => {element.style.fontSize = `${size}px`;});
                }""")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (language, "large-text")
                print(
                    f"PASS {language}: five widths, images, gallery keys, dialog, copy success/failure, FAQ, language picker, large text"
                )

            context.close()
            for language in LANGUAGES:
                context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
                context.route("**/*", local_only)
                page = context.new_page()
                url = base if language == "en" else base + language + "/"
                page.goto(url)
                expect(page.locator(".gallery-controls")).not_to_be_visible()
                expect(page.locator("[data-gallery-panel]:visible")).to_have_count(4)
                for target in LANGUAGES:
                    picker = page.locator(".language-picker")
                    picker.locator("summary").click()
                    picker.locator(f'a[hreflang="{target}"]').click()
                    expected_url = base if target == "en" else base + target + "/"
                    expect(page).to_have_url(expected_url)
                    expect(page.locator("html")).to_have_attribute("lang", target)
                    assert page.goto(url).status == 200
                image_link = page.locator(".hero-figure [data-preview]")
                image_link.click()
                assert page.url.endswith("/screenshots/libraries.png")
                context.close()
            browser.close()
        if errors:
            raise AssertionError(errors)
        (output / "report.json").write_text(
            json.dumps(
                {
                    "responsive_cases": reports,
                    "languages": list(LANGUAGES),
                    "language_navigation": "all language pairs on mobile and desktop; also without JavaScript",
                    "javascript_disabled": "pass",
                    "keyboard_and_dialog": "pass",
                    "clipboard_success_and_failure": "pass",
                    "external_requests": 0,
                    "errors": errors,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"PASS: 25 responsive cases and five JavaScript-disabled language journeys. Evidence: {output}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT / "build/site")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/site-qa")
    args = parser.parse_args()
    verify(args.site, args.output)

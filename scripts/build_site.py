#!/usr/bin/env python3
"""Build an allowlisted, multilingual GitHub Pages site using the standard library."""

import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"en": "English", "fr": "Français", "nl": "Nederlands", "de": "Deutsch", "es": "Español"}
SCREENSHOTS = ("home", "libraries", "review", "sources", "ebooks", "editor", "activity", "mobile-home", "mobile-review")
FILES = (
    "styles.css",
    "site.js",
    "favicon.svg",
    ".nojekyll",
    "images/inkora-home.png",
    *(f"screenshots/{name}.png" for name in SCREENSHOTS),
)
UNCHANGED = {
    "website",
    "Komga",
    "Meta Manager",
    *LANGUAGES.values(),
    "GitHub",
    "↗",
    "↓",
    "⌄",
    "⧉",
    "+",
    "×",
    ".",
    "AniList",
    "MangaDex",
    "MangaUpdates",
    "Open Library",
    "Google Books",
    "BnF",
    "Inkora",
    "01",
    "02",
    "03",
    "compose.yml",
    "localhost:8765",
    "Komga Meta Manager",
    "Inkora ↗",
}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class LocalizedPage(HTMLParser):
    """Translate public copy, preserve code, and keep assets relative to each page."""

    def __init__(self, language: str, catalogue: dict[str, str]):
        super().__init__(convert_charrefs=True)
        self.language = language
        self.catalogue = catalogue
        self.output = []
        self.tags = []
        self.current_language = False

    def translated(self, value: str) -> str:
        """Fail closed on missing copy so a locale cannot silently mix languages."""
        normalized = " ".join(value.split())
        if self.language == "en" or not normalized or normalized in UNCHANGED:
            return value
        if normalized not in self.catalogue:
            raise ValueError(f"Missing {self.language} translation: {normalized}")
        leading = value[: len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()) :]
        return leading + self.catalogue[normalized] + trailing

    def handle_decl(self, declaration):
        self.output.append(f"<!{declaration}>")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            values["lang"] = self.language
        if tag == "span" and "data-current-language" in values:
            self.current_language = True
        if tag == "a" and "hreflang" in values:
            values.pop("aria-current", None)
            if values["hreflang"] == self.language:
                values["aria-current"] = "page"
        for key in ("alt", "aria-label"):
            if values.get(key):
                values[key] = self.translated(values[key])
        if tag == "meta" and (
            values.get("name") == "description" or values.get("property") in {"og:title", "og:description"}
        ):
            values["content"] = self.translated(values["content"])
        for key in ("src", "href"):
            target = values.get(key)
            if target and self.language != "en" and not target.startswith("#") and not urlsplit(target).scheme:
                values[key] = "../" if target == "./" else "../" + target
        rendered = "".join(
            f" {key}" if value is None else f' {key}="{html.escape(value, quote=True)}"'
            for key, value in values.items()
        )
        self.output.append(f"<{tag}{rendered}>")
        if tag not in VOID_TAGS:
            self.tags.append(tag)

    def handle_endtag(self, tag):
        if tag == "head":
            for language in (*LANGUAGES, "x-default"):
                folder = "" if language in ("en", "x-default") else f"{language}/"
                prefix = "./" if self.language == "en" else "../"
                self.output.append(f'<link rel="alternate" hreflang="{language}" href="{prefix}{folder}">\n')
        self.output.append(f"</{tag}>")
        if tag == "span":
            self.current_language = False
        if self.tags and self.tags[-1] == tag:
            self.tags.pop()

    def handle_data(self, data):
        if any(tag in self.tags for tag in ("script", "style", "code", "svg")):
            self.output.append(
                data if "script" in self.tags or "style" in self.tags else html.escape(data, quote=False)
            )
        elif self.current_language:
            self.output.append(LANGUAGES[self.language])
        else:
            self.output.append(html.escape(self.translated(data), quote=False))


class PageLinks(HTMLParser):
    """Collect references for an offline check of every language and local asset."""

    def __init__(self):
        super().__init__()
        self.targets = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            if attrs["id"] in self.ids:
                raise ValueError(f"Duplicate HTML id: {attrs['id']}")
            self.ids.add(attrs["id"])
        self.targets.extend(attrs[key] for key in ("src", "href") if attrs.get(key))


def validate_site(destination: Path) -> None:
    """Verify project-prefix-safe URLs, local files, and fragment destinations."""
    for page in destination.rglob("*.html"):
        links = PageLinks()
        links.feed(page.read_text(encoding="utf-8"))
        for target in links.targets:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            if parsed.path.startswith("/"):
                raise ValueError(f"Root-relative URL breaks GitHub project Pages: {target}")
            asset = (page.parent / unquote(parsed.path)).resolve() if parsed.path else page.resolve()
            if asset.is_dir():
                asset /= "index.html"
            if not asset.is_relative_to(destination.resolve()) or not asset.is_file():
                raise ValueError(f"Missing or out-of-site reference in {page.name}: {target}")
            if parsed.fragment:
                target_links = links
                if asset != page.resolve():
                    target_links = PageLinks()
                    target_links.feed(asset.read_text(encoding="utf-8"))
                if parsed.fragment not in target_links.ids:
                    raise ValueError(f"Missing fragment: {target}")


def build(destination: Path, source: Path = ROOT / "docs") -> None:
    """Assemble only reviewed public assets; never overwrite an existing output."""
    destination, source = destination.resolve(), source.resolve()
    if (
        destination == ROOT
        or destination in ROOT.parents
        or destination == source
        or destination.is_relative_to(source)
    ):
        raise ValueError("Destination must be outside the source directory and cannot contain the repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Destination must be empty; choose a fresh build directory")
    template = (source / "index.html").read_text(encoding="utf-8")
    # Resolve every translation before creating the artifact.
    pages = {}
    for language in LANGUAGES:
        catalogue = (
            {}
            if language == "en"
            else json.loads((source / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        )
        page = LocalizedPage(language, catalogue)
        page.feed(template)
        pages[language] = "".join(page.output)
    destination.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    for language, content in pages.items():
        target = destination / ("index.html" if language == "en" else f"{language}/index.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    validate_site(destination)
    print(f"Built and checked {len(pages)} languages in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/site")
    args = parser.parse_args()
    build(args.output)

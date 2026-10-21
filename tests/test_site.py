"""Public-site assembly, translation completeness and project-relative URL checks."""

import json
import shutil

import pytest

from scripts.build_site import FILES, LANGUAGES, ROOT, build, check_generated, generate, validate_site


def test_committed_docs_can_be_published_directly_without_missing_languages():
    check_generated()
    validate_site(ROOT / "docs")


def test_site_build_has_only_public_assets_and_five_complete_languages(tmp_path):
    destination = tmp_path / "site"
    build(destination)
    expected = {*FILES, "index.html", *(f"{language}/index.html" for language in LANGUAGES if language != "en")}
    actual = {str(file.relative_to(destination)) for file in destination.rglob("*") if file.is_file()}
    assert actual == expected
    assert not (destination / "locales").exists()
    assert not (destination / "USAGE.md").exists()
    for language, label in LANGUAGES.items():
        page = destination / ("index.html" if language == "en" else f"{language}/index.html")
        content = page.read_text()
        assert f'<html lang="{language}">' in content
        assert f"data-current-language>{label}</span>" in content
        assert f'hreflang="{language}" lang="{language}" aria-current="page"' in content
        assert "simon-verbois.github.io/inkora/" in content
        assert "github.com/simon-verbois/inkora" in content
        assert "simonverbois/komga-meta-manager:latest" in content
        assert "./config:/config" in content
        asset_path = "../screenshots/libraries.png" if language != "en" else "screenshots/libraries.png"
        assert asset_path in content
    validate_site(destination)


def test_site_build_keeps_an_existing_destination_untouched(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("Existing work")
    with pytest.raises(ValueError, match="empty"):
        build(tmp_path)
    assert marker.read_text() == "Existing work"
    assert list(tmp_path.iterdir()) == [marker]


@pytest.mark.parametrize("destination", [ROOT, ROOT.parent, ROOT / "docs", ROOT / "docs/nested"])
def test_site_build_rejects_source_and_ancestor_destinations(destination):
    with pytest.raises(ValueError, match="outside"):
        build(destination)


def test_site_build_rejects_missing_translation_before_writing(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "docs", source)
    catalogue_path = source / "locales/fr.json"
    catalogue = json.loads(catalogue_path.read_text())
    del catalogue["Skip to content"]
    catalogue_path.write_text(json.dumps(catalogue))
    destination = tmp_path / "site"
    with pytest.raises(ValueError, match="Missing fr translation: Skip to content"):
        build(destination, source)
    assert not destination.exists()


@pytest.mark.parametrize("condition", ["missing", "stale", "template"])
def test_site_build_rejects_outdated_pages_until_regenerated(tmp_path, condition):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "docs", source)
    page = source / "fr/index.html"
    if condition == "missing":
        page.unlink()
    elif condition == "stale":
        page.write_text("Outdated French page")
    else:
        template = source / "site-template.html"
        template.write_text(template.read_text().replace("<body>", '<body class="updated">'))
    destination = tmp_path / "site"
    with pytest.raises(ValueError, match="Stale localized page"):
        build(destination, source)
    assert not destination.exists()
    generate(source)
    check_generated(source)
    validate_site(source)
    build(destination, source)
    assert (destination / "fr/index.html").read_text() == page.read_text()


@pytest.mark.parametrize("target", ["/screenshots/libraries.png", "missing.png", "#missing-section", "../outside.txt"])
def test_site_validation_rejects_broken_and_out_of_site_links(tmp_path, target):
    (tmp_path / "index.html").write_text(f'<a href="{target}">A link</a>')
    with pytest.raises(ValueError):
        validate_site(tmp_path)

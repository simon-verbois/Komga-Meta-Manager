from unittest.mock import AsyncMock, Mock, patch

import deepl
import pytest

from modules.config import DeepLConfig
from modules.translators import get_translator
from modules.translators.deepl import DeepLTranslator
from modules.translators.google import GoogleTranslator


def test_google_translation_cache_and_api(tmp_path) -> None:
    with patch("modules.translators.google.GoogletransTranslator") as constructor:
        translator = GoogleTranslator()
    translator.cache_path = tmp_path / "google.json"
    translator.translator = constructor.return_value
    translator.translator.translate.return_value = Mock(text="Bonjour")

    assert translator.translate("Hello", "fr") == "Bonjour"
    assert translator.translate("Hello", "fr") == "Bonjour"
    assert translator.cache_hits == 1
    translator.save_cache_to_disk()
    assert (tmp_path / "google.json").exists()


def test_google_unsupported_language_returns_original() -> None:
    translator = GoogleTranslator.__new__(GoogleTranslator)
    translator.translator = Mock()
    translator.cache = {}
    translator.cache_hits = translator.cache_misses = translator.unsaved_changes = 0
    assert translator.translate("Hello", "not-a-language") == "Hello"


def test_google_skips_api_when_source_already_matches_target() -> None:
    translator = GoogleTranslator.__new__(GoogleTranslator)
    translator.translator = Mock()
    translator.cache = {}
    translator.cache_hits = translator.cache_misses = translator.unsaved_changes = 0

    assert translator.translate("Résumé français", "fr", source_language="FR-fr") == "Résumé français"
    translator.translator.translate.assert_not_called()
    assert translator.cache_misses == 0


def test_google_forces_known_source_language_for_ambiguous_text() -> None:
    translator = GoogleTranslator.__new__(GoogleTranslator)
    translator.translator = Mock()
    translator.translator.translate.return_value = Mock(text="Fils")
    translator.cache = {}
    translator.cache_hits = translator.cache_misses = translator.unsaved_changes = 0

    assert translator.translate("Son", "fr", source_language="en-US") == "Fils"
    translator.translator.translate.assert_called_once_with("Son", dest="fr", src="en")


def test_google_async_api_is_bridged_to_sync() -> None:
    translator = GoogleTranslator.__new__(GoogleTranslator)
    translator.translator = Mock()
    translator.translator.translate = AsyncMock(return_value=Mock(text="Bonjour"))
    assert translator._translate_with_retry("Hello", "fr") == "Bonjour"


def test_deepl_translation_cache_and_api(tmp_path) -> None:
    with patch("modules.translators.deepl.deepl.Translator") as constructor:
        translator = DeepLTranslator(DeepLConfig(api_key="secret"))
    translator.cache_path = tmp_path / "deepl.json"
    translator.translator = constructor.return_value
    translator.translator.translate_text.return_value = Mock(text="Bonjour")

    assert translator.translate("Hello", "FR") == "Bonjour"
    assert translator.translate("Hello", "FR") == "Bonjour"
    translator.save_cache_to_disk()
    assert (tmp_path / "deepl.json").exists()


def test_deepl_skips_api_when_source_already_matches_target() -> None:
    translator = DeepLTranslator.__new__(DeepLTranslator)
    translator.unavailable = False
    translator.translator = Mock()
    translator.cache = {}
    translator.cache_hits = translator.cache_misses = translator.unsaved_changes = 0

    assert translator.translate("Résumé français", "FR-FR", source_language="fr") == "Résumé français"
    translator.translator.translate_text.assert_not_called()
    assert translator.cache_misses == 0


def test_deepl_forces_known_source_language_for_ambiguous_text() -> None:
    translator = DeepLTranslator.__new__(DeepLTranslator)
    translator.unavailable = False
    translator.translator = Mock()
    translator.translator.translate_text.return_value = Mock(text="Fils")
    translator.cache = {}
    translator.cache_hits = translator.cache_misses = translator.unsaved_changes = 0

    assert translator.translate("Son", "FR-FR", source_language="en-US") == "Fils"
    translator.translator.translate_text.assert_called_once_with("Son", target_lang="FR-FR", source_lang="EN")


def test_translator_factory_handles_supported_and_unknown_providers() -> None:
    with patch("modules.translators.GoogleTranslator") as google:
        google.return_value.translator = Mock()
        assert get_translator("google") is google.return_value
    with patch("modules.translators.DeepLTranslator") as deepl:
        deepl.return_value.translator = Mock()
        assert get_translator("deepl", config=DeepLConfig(api_key="secret")) is deepl.return_value
    assert get_translator("deepl") is None
    assert get_translator("unknown") is None


@pytest.mark.parametrize("failure", [deepl.QuotaExceededException, deepl.AuthorizationException])
def test_deepl_permanent_account_failure_falls_back_once_and_stops_api_calls(tmp_path, failure, caplog):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogleTranslator") as google,
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"))
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.side_effect = failure("private text should not be logged")
        google.return_value.translate.side_effect = ["Bonjour", "Autre texte"]
        assert primary.translate("Hello", "FR", source_language="en") == "Bonjour"
        assert primary.translate("Another text", "FR", source_language="en") == "Autre texte"
        sdk.return_value.translate_text.assert_called_once()
        google.assert_called_once()
        assert google.return_value.translate.call_args_list[0].args == ("Hello", "fr")
        assert google.return_value.translate.call_args_list[0].kwargs == {"source_language": "en"}
        assert primary.cache == {}  # Google translations never pollute the DeepL cache.
        assert "private text" not in caplog.text


def test_deepl_fallback_disabled_keeps_original_text(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogleTranslator") as google,
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"), fallback_to_google=False)
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.side_effect = deepl.QuotaExceededException("Quota exhausted")
        assert primary.translate("Hello", "FR") == "Hello"
        assert primary.translate("More", "FR") == "More"
        google.assert_not_called()
        sdk.return_value.translate_text.assert_called_once()


def test_deepl_transient_failure_uses_bounded_retries_before_fallback(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogleTranslator") as google,
        patch("time.sleep"),
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"))
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.side_effect = deepl.DeepLException("Unavailable", http_status_code=503)
        google.return_value.translate.return_value = "Bonjour"
        assert primary.translate("Hello", "FR") == "Bonjour"
        assert sdk.return_value.translate_text.call_count == 3
        google.return_value.translate.assert_called_once()


def test_deepl_success_and_matching_language_do_not_initialize_google(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogleTranslator") as google,
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"))
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.return_value = Mock(text="Bonjour")
        assert primary.translate("Hello", "FR") == "Bonjour"
        assert primary.translate("Déjà français", "FR", source_language="fr") == "Déjà français"
        google.assert_not_called()


def test_fallback_google_cache_is_reused_and_saved_separately(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogletransTranslator") as google,
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"))
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.side_effect = deepl.QuotaExceededException("Quota exhausted")
        google.return_value.translate.return_value = Mock(text="Bonjour")
        assert primary.translate("Hello", "FR") == "Bonjour"
        primary.fallback.cache_path = tmp_path / "google.json"
        assert primary.translate("Hello", "FR") == "Bonjour"
        google.return_value.translate.assert_called_once_with("Hello", dest="fr")
        primary.save_cache_to_disk()
        assert (tmp_path / "google.json").exists()
        assert not (tmp_path / "deepl.json").exists()
        primary.cache["v2:auto:FR:Cached text"] = "Texte en cache"
        assert primary.translate("Cached text", "FR") == "Texte en cache"


def test_both_translation_services_failing_keep_original_text(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator") as sdk,
        patch("modules.translators.google.GoogleTranslator") as google,
    ):
        primary = DeepLTranslator(DeepLConfig(api_key="test-key"))
        primary.cache_path = tmp_path / "deepl.json"
        sdk.return_value.translate_text.side_effect = deepl.QuotaExceededException("Quota exhausted")
        google.return_value.translate.side_effect = RuntimeError("Unavailable")
        assert primary.translate("Original text", "FR") == "Original text"
        assert primary.cache == {}


def test_deepl_initialization_failure_can_still_use_google(tmp_path):
    with (
        patch("modules.translators.deepl.deepl.Translator", side_effect=ValueError("Invalid client")),
        patch("modules.translators.google.GoogleTranslator") as google,
    ):
        google.return_value.translate.return_value = "Bonjour"
        primary = get_translator("deepl", config=DeepLConfig(api_key="test-key"))
        assert primary is not None
        primary.cache_path = tmp_path / "deepl.json"
        assert primary.translate("Hello", "FR") == "Bonjour"
        assert get_translator("deepl", config=DeepLConfig(api_key="test-key"), fallback_to_google=False) is None

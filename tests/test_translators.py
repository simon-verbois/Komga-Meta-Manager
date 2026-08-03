from unittest.mock import AsyncMock, Mock, patch

from modules.config import DeepLConfig
from modules.translators import get_translator
from modules.translators.deepl import DeepLTranslator
from modules.translators.google import GoogleTranslator


def test_google_translation_cache_manual_and_api(tmp_path) -> None:
    with patch("modules.translators.google.GoogletransTranslator") as constructor:
        translator = GoogleTranslator()
    translator.cache_path = tmp_path / "google.json"
    translator.translator = constructor.return_value
    translator.translator.translate.return_value = Mock(text="Bonjour")

    with patch("modules.translators.google.MANUAL_TRANSLATIONS", {"fr": {"Manual": "Manuel"}}):
        assert translator.translate("Manual", "fr-FR") == "Manuel"
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


def test_google_async_api_is_bridged_to_sync() -> None:
    translator = GoogleTranslator.__new__(GoogleTranslator)
    translator.translator = Mock()
    translator.translator.translate = AsyncMock(return_value=Mock(text="Bonjour"))
    assert translator._translate_with_retry("Hello", "fr") == "Bonjour"


def test_deepl_translation_cache_manual_and_api(tmp_path) -> None:
    with patch("modules.translators.deepl.deepl.Translator") as constructor:
        translator = DeepLTranslator(DeepLConfig(api_key="secret"))
    translator.cache_path = tmp_path / "deepl.json"
    translator.translator = constructor.return_value
    translator.translator.translate_text.return_value = Mock(text="Bonjour")

    with patch("modules.translators.deepl.MANUAL_TRANSLATIONS", {"fr": {"Manual": "Manuel"}}):
        assert translator.translate("Manual", "FR-FR") == "Manuel"
    assert translator.translate("Hello", "FR") == "Bonjour"
    assert translator.translate("Hello", "FR") == "Bonjour"
    translator.save_cache_to_disk()
    assert (tmp_path / "deepl.json").exists()


def test_translator_factory_handles_supported_and_unknown_providers() -> None:
    with patch("modules.translators.GoogleTranslator") as google:
        google.return_value.translator = Mock()
        assert get_translator("google") is google.return_value
    with patch("modules.translators.DeepLTranslator") as deepl:
        deepl.return_value.translator = Mock()
        assert get_translator("deepl", config=DeepLConfig(api_key="secret")) is deepl.return_value
    assert get_translator("deepl") is None
    assert get_translator("unknown") is None

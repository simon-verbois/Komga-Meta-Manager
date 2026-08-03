from modules.models import MetadataCandidate, MetadataRecord
from modules.providers.base import MetadataProvider, MetadataProviderError


class EmptyProvider(MetadataProvider):
    def __init__(self, cache_dir):
        self.calls = 0
        super().__init__(cache_dir, 1)

    def _perform_search(self, search_term: str) -> list[MetadataCandidate]:
        self.calls += 1
        return []

    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        raise AssertionError("not used")


class FailingProvider(EmptyProvider):
    def _perform_search(self, search_term: str) -> list[MetadataCandidate]:
        self.calls += 1
        raise MetadataProviderError("offline")


class DetailProvider(EmptyProvider):
    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        self.calls += 1
        return MetadataRecord(
            provider="test",
            external_id=external_id,
            titles=["Cached"],
        )


class FailingDetailProvider(EmptyProvider):
    def _perform_get_metadata(self, external_id: str) -> MetadataRecord:
        self.calls += 1
        raise MetadataProviderError("offline")


def test_successful_empty_results_are_cached(tmp_path) -> None:
    provider = EmptyProvider(tmp_path)
    assert provider.search("Unknown") == []
    assert provider.search("Unknown") == []
    assert provider.calls == 1


def test_legacy_search_results_without_alternative_titles_are_ignored(tmp_path) -> None:
    provider = EmptyProvider(tmp_path)
    provider.cache.set("search:v2:Alias", [{
        "provider": "test",
        "external_id": "stale",
        "titles": ["Primary title"],
    }])

    assert provider.search("Alias") == []
    assert provider.calls == 1


def test_provider_failures_are_not_cached(tmp_path) -> None:
    provider = FailingProvider(tmp_path)
    for _ in range(2):
        try:
            provider.search("Unknown")
        except MetadataProviderError:
            pass
    assert provider.calls == 2


def test_provider_details_are_cached(tmp_path) -> None:
    provider = DetailProvider(tmp_path)
    assert provider.get_by_id("uuid").external_id == "uuid"
    assert provider.get_by_id("uuid").external_id == "uuid"
    assert provider.calls == 1


def test_provider_detail_failures_are_not_cached(tmp_path) -> None:
    provider = FailingDetailProvider(tmp_path)
    for _ in range(2):
        try:
            provider.get_by_id("uuid")
        except MetadataProviderError:
            pass
    assert provider.calls == 2

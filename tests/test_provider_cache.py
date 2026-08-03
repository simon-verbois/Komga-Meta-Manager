from modules.models import AniListMedia
from modules.providers.base import MetadataProvider, MetadataProviderError


class EmptyProvider(MetadataProvider):
    def __init__(self, cache_dir):
        self.calls = 0
        super().__init__(cache_dir, 1)

    def _perform_search(self, search_term: str) -> list[AniListMedia]:
        self.calls += 1
        return []


class FailingProvider(EmptyProvider):
    def _perform_search(self, search_term: str) -> list[AniListMedia]:
        self.calls += 1
        raise MetadataProviderError("offline")


def test_successful_empty_results_are_cached(tmp_path) -> None:
    provider = EmptyProvider(tmp_path)
    assert provider.search("Unknown") == []
    assert provider.search("Unknown") == []
    assert provider.calls == 1


def test_provider_failures_are_not_cached(tmp_path) -> None:
    provider = FailingProvider(tmp_path)
    for _ in range(2):
        try:
            provider.search("Unknown")
        except MetadataProviderError:
            pass
    assert provider.calls == 2


"""
Unit tests for field removal functionality in processor.py
"""
import pytest
from unittest.mock import Mock, MagicMock
from modules.config import ProcessingConfig, UpdateFlags, AppConfig, SystemConfig, ProviderConfig, KomgaConfig
from modules.processor import _remove_summary, _remove_genres, _remove_tags, _remove_status, _remove_age_rating, process_single_series
from modules.models import KomgaSeries, KomgaSeriesMetadata


class TestFieldRemoval:
    """Tests for the field removal functionality."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Create mock configuration with remove_fields enabled
        processing_config = ProcessingConfig(
            remove_fields=UpdateFlags(
                summary=True,
                genres=True,
                tags=True,
                status=True,
                age_rating=True,
                cover_image=False
            ),
            force_unlock=True
        )

        self.config = AppConfig(
            system=SystemConfig(dry_run=False),
            processing=processing_config,
            provider=ProviderConfig(),
            komga=KomgaConfig(url="http://test", api_key="test", libraries=["test"])
        )

        # Create mock series with metadata
        self.series = KomgaSeries(
            id="test-series-id",
            name="Test Series",
            metadata=KomgaSeriesMetadata(
                summary="Existing summary",
                genres=["Existing Genre"],
                tags=["Existing Tag"],
                status="ONGOING",
                age_rating=12,
                summary_lock=False,
                genres_lock=False,
                tags_lock=False,
                status_lock=False,
                age_rating_lock=False
            )
        )

        self.payload = {}

    def test_remove_summary_success(self):
        """Test successful summary removal."""
        result = _remove_summary(self.payload, self.series, self.config)

        assert result == "- Summary: Will be removed."
        assert self.payload['summary'] == ""

    def test_remove_summary_locked_with_force_unlock(self):
        """Test summary removal when locked but force_unlock is enabled."""
        self.series.metadata.summary_lock = True

        result = _remove_summary(self.payload, self.series, self.config)

        assert result == "- Summary: Will be removed."
        assert self.payload['summary'] == ""
        assert self.payload['summaryLock'] == False

    def test_remove_summary_locked_without_force_unlock(self):
        """Test summary removal blocked when locked and force_unlock disabled."""
        self.series.metadata.summary_lock = True
        self.config.processing.force_unlock = False

        result = _remove_summary(self.payload, self.series, self.config)

        assert result is None
        assert 'summary' not in self.payload

    def test_remove_genres_success(self):
        """Test successful genres removal."""
        result = _remove_genres(self.payload, self.series, self.config)

        assert result == "- Genres: Will be removed."
        assert self.payload['genres'] == []

    def test_remove_tags_success(self):
        """Test successful tags removal."""
        result = _remove_tags(self.payload, self.series, self.config)

        assert result == "- Tags: Will be removed."
        assert self.payload['tags'] == []

    def test_remove_status_success(self):
        """Test successful status removal."""
        result = _remove_status(self.payload, self.series, self.config)

        assert result == "- Status: Will be removed."
        assert self.payload['status'] is None

    def test_remove_age_rating_success(self):
        """Test successful age rating removal."""
        result = _remove_age_rating(self.payload, self.series, self.config)

        assert result == "- Age Rating: Will be removed."
        assert self.payload['ageRating'] is None

    def test_remove_disabled_in_config(self):
        """Test that removal is skipped when disabled in config."""
        self.config.processing.remove_fields.summary = False

        result = _remove_summary(self.payload, self.series, self.config)

        assert result is None
        assert 'summary' not in self.payload

    def test_priority_in_process_single_series(self):
        """Test that removal takes priority over updates in process_single_series."""
        # Mock provider and translator
        provider = Mock()
        provider.search.return_value = None  # No match found, so no updates

        translator = Mock()

        # Create komga client mock
        komga_client = Mock()

        # Series with existing metadata
        series_with_data = KomgaSeries(
            id="test-series-id",
            name="Test Series",
            metadata=KomgaSeriesMetadata(
                summary="Existing summary",
                genres=["Existing Genre"],
                summary_lock=False,
                genres_lock=False
            )
        )

        # Process series - removal should happen even though no match
        result = process_single_series(series_with_data, self.config, komga_client, provider, translator)

        # Should return changes list (not None) since removal will happen
        assert result is not None

        # Check that removal operations were prepared
        changes = [change for change in result if 'removed' in change.lower() or 'Summary: Will be removed' in change or 'Genres: Will be removed' in change]
        assert len(changes) > 0

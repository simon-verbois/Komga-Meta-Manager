# -*- coding: utf-8 -*-
"""
Tests for the processor module.
"""
import logging
import pytest
from unittest.mock import Mock, patch, MagicMock
from thefuzz import fuzz

logger = logging.getLogger(__name__)

from modules.processor import choose_best_match, should_update_field
from modules.models import AniListMedia, AniListTitle


class TestChooseBestMatch:
    """Test the fuzzy matching logic for selecting best AniList matches."""

    def create_mock_anilist_media(self, romaji_title, english_title, popularity=50):
        """Helper to create mock AniListMedia objects."""
        title = AniListTitle(
            romaji=romaji_title,
            english=english_title,
            native=None
        )
        return AniListMedia(
            id=123,
            title=title,
            description="Test description",
            status="FINISHED",
            genres=["Action"],
            tags=[],
            popularity=popularity,
            isAdult=False,
            coverImage=None
        )

    def test_exact_match_returns_best_candidate(self):
        """Test that exact matches are preferred."""
        series_title = "One Piece"
        candidates = [
            self.create_mock_anilist_media("One Piece", "One Piece", popularity=100),
        ]

        result = choose_best_match(series_title, candidates, min_score=80)
        assert result is not None
        assert result.title.english == "One Piece"

    def test_high_score_english_title_preferred(self):
        """Test that high-scoring English titles are preferred."""
        series_title = "Naruto Shippuden"
        candidates = [
            self.create_mock_anilist_media("Naruto Shippuuden", "Naruto Shippuden", popularity=80),  # Score ~97
            self.create_mock_anilist_media("Some Other Anime", "Some Other Anime", popularity=90),  # Score ~37
        ]

        result = choose_best_match(series_title, candidates, min_score=80)
        assert result is not None
        assert result.title.english == "Naruto Shippuden"

    def test_popularity_tiebreaker(self):
        """Test that popularity breaks ties when scores are equal."""
        series_title = "Test Manga"
        candidates = [
            self.create_mock_anilist_media("Test Manga A", "Test Manga A", popularity=50),
            self.create_mock_anilist_media("Test Manga B", "Test Manga B", popularity=100),
        ]

        # Both should have the same score, higher popularity should win
        result = choose_best_match(series_title, candidates, min_score=80)
        assert result is not None
        assert result.title.english == "Test Manga B"

    def test_low_score_candidates_filtered_out(self):
        """Test that candidates below min_score are filtered out."""
        series_title = "Very Specific Title"
        candidates = [
            self.create_mock_anilist_media("Completely Different Title", "Different", popularity=100),
        ]

        result = choose_best_match(series_title, candidates, min_score=80)
        assert result is None

    def test_empty_candidates_list(self):
        """Test behavior with empty candidates list."""
        result = choose_best_match("Any Title", [], min_score=80)
        assert result is None

    def test_candidates_with_none_titles_filtered(self):
        """Test that candidates with None titles are handled gracefully."""
        title_none = AniListTitle(romaji=None, english=None, native=None)
        media_none_title = AniListMedia(
            id=123,
            title=title_none,
            description="Test",
            status="FINISHED",
            genres=[],
            tags=[],
            popularity=50,
            isAdult=False,
            coverImage=None
        )

        candidates = [
            media_none_title,
            self.create_mock_anilist_media("Valid Title", "Valid Title", popularity=80)
        ]

        result = choose_best_match("Valid Title", candidates, min_score=80)
        assert result is not None
        assert result.title.english == "Valid Title"


class TestShouldUpdateField:
    """Test the logic for determining if metadata fields should be updated."""

    def test_unlocked_empty_field_should_update(self):
        """Test that unlocked empty fields are updated."""
        assert should_update_field("", False, Mock()) == True

    def test_locked_field_no_force_should_not_update(self):
        """Test that locked fields are not updated unless force is enabled."""
        config = Mock()
        config.processing.force_unlock = False
        assert should_update_field("existing", True, config) == False

    def test_locked_field_force_update(self):
        """Test that locked fields are updated when force_unlock is enabled."""
        config = Mock()
        config.processing.force_unlock = True
        assert should_update_field("existing", True, config) == True

    def test_overwrite_existing_enabled(self):
        """Test that existing fields are overwritten when configured."""
        config = Mock()
        config.processing.force_unlock = False
        config.processing.overwrite_existing = True
        assert should_update_field("existing", False, config) == True

    def test_overwrite_disabled_keeps_existing(self):
        """Test that existing fields are preserved when overwrite is disabled."""
        config = Mock()
        config.processing.force_unlock = False
        config.processing.overwrite_existing = False
        assert should_update_field("existing", False, config) == False

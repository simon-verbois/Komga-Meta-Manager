# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2025-10-

### Added
- Support for fetching and updating authors metadata

### Changed
- **Major architecture refactoring** of `processor.py`:
  - Replaced duplicated `_update_*` and `_remove_*` functions with generic `FieldHandler` dataclass system
  - Introduced `SummaryHandler`, `GenresHandler`, `StatusHandler`, `TagsHandler`, `AgeRatingHandler` subclasses
  - Reduced code complexity by ~300 lines while maintaining all functionality
  - Improved maintainability: adding new metadata fields now requires only creating a new handler class
  - Enhanced type safety and error handling across all field processing
- Updated project documentation to reflect Docker-only deployment
- Refined tooling and quality guidelines for development

### Fixed
- Fixed `ageRating` attribute access error in FieldHandler processing

## [0.3.0] - 2025-10-16

### Added
- Implemented comprehensive circuit breaker system for API resilience
- Metadata provider cache system
- Settings to select which fields should be updated
- Ability to update cover image
- Added `remove_fields` configuration option to completely clear metadata fields

### Changed
- Complete project structure refactoring:
  - Moved from `src/manga_manager/` to `modules/` at project root for cleaner organization
  - Updated all imports across the codebase (`manga_manager.xxx` → `modules.xxx`)
  - Simplified package structure while maintaining all functionality
  - Updated `.gitignore` with comprehensive Python-specific ignore patterns
- Updated Dockerfile to reflect new `modules/` structure

## [0.2.0] - 2025-10-14

### Added
- Support for DeepL translator
- Improved title matching logic
- Added Changelog section to README.md

### Changed
- Improved translation cache system to avoid useless translation API calls

## [0.1.0] - 2025-10-12

### Added
- Initial release of Komga Meta Manager
- Automated metadata fetching from AniList (Title, Summary, Status, Genres, Tags)
- Targeted processing for specified Komga libraries
- Translation support (Google Translate)
- Smart updates (fill empty or overwrite existing)
- Persistent translation caching
- Flexible operation (manual run or daily scheduler)
- Dry-run mode

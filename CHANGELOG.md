# Changelog

## [0.3.0] - 2025-10-14

### Added
- Add metadata provider cache system.
- Add settings to select which fields should be updated.
- Add ability to update cover image.

### Changed
- Move caches in dedicated folder

### Fixed

### Removed
- Remove skip_series_with_summary settings, replaced by exclude_series


## [0.2.0] - 2025-10-14

### Added
- Support for DeepL translator.
- Improved title matching logic.
- Added a Changelog section to README.md.

### Changed
- Improve translation cache system to avoid useless translation API call.

### Fixed

### Removed

### Security

## [0.1.0] - 2025-10-12

### Added
- Initial release of Komga Meta Manager.
- Automated metadata fetching from AniList (Title, Summary, Status, Genres, Tags).
- Targeted processing for specified Komga libraries.
- Translation support (Google Translate).
- Smart updates (fill empty or overwrite existing).
- Persistent translation caching.
- Flexible operation (manual run or daily scheduler).
- Dry-run mode.

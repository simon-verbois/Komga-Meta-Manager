# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Circuit Breaker Pattern**: Implemented comprehensive circuit breaker system for API resilience
  - Protection against cascading failures for Komga, AniList, and translation APIs
  - Configurable failure thresholds, recovery timeouts, and success criteria
  - Thread-safe implementation with detailed metrics tracking
  - State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED) for intelligent failure recovery
- **Metadata provider cache system**
- **Settings to select which fields should be updated**
- **Ability to update cover image**

### Changed
- **Complete project structure refactoring**:
  - Moved from `src/manga_manager/` to `modules/` at project root for cleaner organization
  - Updated all imports across the codebase (`manga_manager.xxx` → `modules.xxx`)
  - Simplified package structure while maintaining all functionality
  - Updated `.gitignore` with comprehensive Python-specific ignore patterns
- **Docker configuration**: Updated Dockerfile to reflect new `modules/` structure
  - Changed source copy path from `./src/manga_manager` to `./modules`
  - Updated entrypoint from `manga_manager.main` to `modules.main`

## [0.2.0] - 2025-10-14

### Added
- **Support for DeepL translator**
- **Improved title matching logic**
- **Added Changelog section to README.md**

### Changed
- **Improved translation cache system to avoid useless translation API calls**

## [0.1.0] - 2025-10-12

### Added
- **Initial release of Komga Meta Manager**
- **Automated metadata fetching from AniList (Title, Summary, Status, Genres, Tags)**
- **Targeted processing for specified Komga libraries**
- **Translation support (Google Translate)**
- **Smart updates (fill empty or overwrite existing)**
- **Persistent translation caching**
- **Flexible operation (manual run or daily scheduler)**
- **Dry-run mode**

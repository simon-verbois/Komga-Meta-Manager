# Changelog

Release notes for Komga Meta Manager. This file and VERSION are included in the Docker image.

<!--
Add an English bullet under "## [Unreleased]" for each user-visible change, in the same commit.
Use the sections Added, Changed, Fixed, and Maintenance as needed. Do not add empty bullets.

scripts/release.sh refuses an empty Unreleased section. It creates a YYYY.W.N version using
ISO year/week and a weekly counter, dates the release heading, and reopens an empty Unreleased
section above it. VERSION and released headings are managed by that script, not edited by hand.
-->

## [Unreleased]

### Added

- Discover Komga libraries automatically in the Web UI and enable or disable processing per library, including disabling all libraries.
- Configure Komga, providers, processing, translation, and scheduling through an English Web UI on port 8765.
- Create a single administrator account on first access and change its password from the Web UI.
- Start manual runs or isolated dry runs and view execution logs and persistent audit history.
- Start and stop the local development environment with start-kmm.sh and stop-kmm.sh.

### Changed

- Store configuration in SQLite and reload it without restarting the container; import existing YAML configuration on first startup.
- Keep the Web UI available when scheduling is disabled or watcher initialization fails.

### Maintenance

- Document mandatory changelog updates and development container rebuilds in AGENTS.md.
- Define the product vision and GUI/UX guidelines for simple metadata management across manga, webtoon, and ebook libraries in AGENTS.md.
- Prepare interface text for future translations and add Web UI regression coverage.
- Automate versioned changelog releases and package version, release notes, and the MIT license in Docker builds.

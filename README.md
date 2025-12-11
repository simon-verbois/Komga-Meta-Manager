<p align="center">
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/graphs/traffic"><img src="https://api.visitorbadge.io/api/visitors?path=https%3A%2F%2Fgithub.com%2Fsimon-verbois%2FKomga-Meta-Manager&label=Visitors&countColor=26A65B&style=flat" alt="Visitor Count" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=flat" alt="GitHub Last Commit" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/stargazers"><img src="https://img.shields.io/github/stars/simon-verbois/Komga-Meta-Manager?style=flat&color=yellow" alt="GitHub Stars" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/issues"><img src="https://img.shields.io/github/issues/simon-verbois/Komga-Meta-Manager?style=flat&color=red" alt="GitHub Issues" height="28"/></a>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/pulls"><img src="https://img.shields.io/github/issues-pr/simon-verbois/Komga-Meta-Manager?style=flat&color=blue" alt="GitHub Pull Requests" height="28"/></a>
</p>

# Komga Meta Manager

Automatically enriches Komga manga series metadata using AniList API, with optional translation and persistent caching.

## Features

- **Auto-detection** of series in specified Komga libraries
- **High-performance** fetching with AniList API integration
- **Smart caching** to avoid re-processing and prevent data loss
- **Scheduled processing** or on-demand execution
- **Translation support** using Google Translate or DeepL
- **Docker and Kubernetes ready** for production deployment
- **YAML configuration** for all settings

## Quick Start

### Configuration

See `config/config.yml.template` for all available options with inline comments explaining each parameter.<br>
Rename the template to `config/config.yml`.

### Start

```bash
# Clone repository
git clone <repository-url>
cd Komga-Meta-Manager

# Edit compose and config with your data
vim compose.yml
vim config/config.yml

# Build and run
docker compose up
```

## Deployment

- **Docker**: See compose.yml for production.

## Development

Local build and run with:

```bash
docker compose -f compose-testing.yml build && docker compose -f compose-testing.yml up
```

## License

See LICENSE file.

## Disclaimer

This is a personal automation script I use on my home server to enrich Komga manga series metadata. I'm sharing it with the community as-is, without any warranty or guarantee of maintenance.

This project was developed with the assistance of a self-hosted Mistral AI model.

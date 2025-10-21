# Development Guide - Komga Meta Manager

## 🏗️ Architecture

The project follows a modular architecture with clear separation of responsibilities:

```
modules/
├── constants.py          # Centralized constants
├── config.py             # Configuration and validation
├── main.py               # Main entry point
├── metrics.py            # Metrics collection
├── models.py             # Pydantic data models
├── komga_client.py       # Client for Komga API
├── processor.py          # Main processing logic
├── providers/            # Metadata providers
│   ├── __init__.py      # Factory functions
│   ├── base.py          # Common interface
│   └── anilist.py       # AniList implementation
└── translators/          # Translators
    ├── __init__.py      # Factory functions
    ├── base.py          # Common interface
    ├── google.py        # Google Translate implementation
    └── deepl.py         # DeepL implementation
```


## 🔧 Development

### Environment

**Important:** Komga Meta Manager runs exclusively in Docker containers. No local development or execution is supported.

### Docker Development

All development activities use the provided Docker infrastructure:

#### Development configuration

1. **Build and test:** Use the provided `testing-compose.yml` to build and test changes in a container:
```bash
docker compose -f testing-compose.yml up --build
```

2. **Manual execution:** To quickly test changes:
```bash
docker compose -f compose.yml run --rm komga-meta-manager
```

3. **Debug mode:** Enable detailed logs in your configuration:
```yaml
system:
  debug: true
```

#### Development structure

```
Komga-Meta-Manager/
├── modules/        # Python source code
├── config/         # Configuration and templates
├── compose.yml     # Production Docker
├── testing-compose.yml # Development Docker
└── Dockerfile      # Base image
```

## 🚀 Deployment

### Docker Production

The deployment is done exclusively via Docker:

```bash
# Production
docker compose up -d

# Single execution
docker compose run --rm komga-meta-manager
```

## 📋 Best Practices

### Code

- **Type hints**: Always use type annotations
- **Docstrings**: Document all public functions
- **PEP 8**: Respect Python style conventions
- **Fail fast**: Check preconditions at function start

### Error Handling

- **Specific exceptions**: Create custom exceptions when needed
- **Clear messages**: Provide informative error messages
- **Logging**: Log errors with context
- **Recovery**: Implement recovery strategies when possible

### Performance

- **Cache**: Use cache to avoid repeated calls
- **Metrics**: Profile bottlenecks with metrics
- **Async**: Consider asyncio for massive I/O operations (future)

## 🤝 Contribution

### Workflow

1. Create a feature branch: `git checkout -b feature/feature-name`
2. Implement the functionality with manual testing
3. Test changes manually using the Docker container
4. Submit PR with detailed description

### Commit Conventions

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `test`: Tests
- `refactor`: Refactoring without functional changes
- `perf`: Performance improvement
- `chore`: Maintenance

### Reviews

- All PRs must be reviewed
- Code must follow established patterns and best practices
- Manual testing should validate functionality

## 📊 Monitoring

### Key Metrics

- Average processing time per series
- API call success rate
- Cache hit rates
- Error count by type

### Alerts

- API failure rate > 10%
- Processing time > 2x average
- Cache hit rate < 50%

See `metrics.py` for complete implementation.

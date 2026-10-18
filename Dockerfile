# --- Build Stage ---
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt


# --- Final Stage ---
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

WORKDIR /app

RUN groupadd --system --gid 1000 appgroup && useradd --system --uid 1000 --gid appgroup appuser

ARG BUILD_VERSION=development
ARG BUILD_REVISION=unknown

LABEL org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.licenses="MIT"

COPY --chown=appuser:appgroup VERSION CHANGELOG.md LICENSE ./
RUN if [ "$BUILD_VERSION" != "development" ]; then test "$BUILD_VERSION" = "$(cat VERSION)"; fi

COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv
COPY --chown=appuser:appgroup ./modules ./modules

USER appuser

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8765

CMD [ "python", "-m", "modules.main" ]

# --- Build Stage ---
FROM python:3.11.15-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt


# --- Final Stage ---
FROM python:3.11.15-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

WORKDIR /app

RUN groupadd --system --gid 1000 appgroup && useradd --system --uid 1000 --gid appgroup appuser

COPY --chown=appuser:appgroup ./VERSION ./VERSION

COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv
COPY --chown=appuser:appgroup ./modules ./modules

USER appuser

ENV PATH="/opt/venv/bin:$PATH"

CMD [ "python", "-m", "modules.main" ]

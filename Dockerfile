# --- Build Stage ---
FROM python:3.11.9-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# --- Final Stage ---
FROM python:3.11.9-slim

WORKDIR /app

RUN groupadd --system --gid 1000 appgroup && useradd --system --uid 1000 --gid appgroup appuser

COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv
COPY --chown=appuser:appgroup ./modules ./modules
COPY --chown=appuser:appgroup ./VERSION ./VERSION

USER appuser

ENV PATH="/opt/venv/bin:$PATH"

CMD [ "python", "-m", "modules.main" ]
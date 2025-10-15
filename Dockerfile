# --- Build Stage ---
# Use a specific version for better reproducibility
FROM python:3.11.9-slim as builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
# Use a virtual environment to isolate packages
RUN python -m venv /opt/venv
# Ensure the venv binary is on the PATH
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# --- Final Stage ---
FROM python:3.11.9-slim

WORKDIR /app

# Create a non-root user and group
RUN groupadd --system --gid 1000 appgroup && useradd --system --uid 1000 --gid appgroup appuser

# Copy installed dependencies from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy source code
# We copy it into a 'modules' subdirectory to make the python -m command work correctly
COPY ./modules ./modules

# Change ownership of the app directory
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Set path to include the virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Command to run the application as a module
CMD [ "python", "-m", "modules.main" ]

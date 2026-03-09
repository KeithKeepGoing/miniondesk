FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash minion

WORKDIR /app

# Install Python deps first (layer caching)
COPY runner/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy runner code
COPY runner/ ./

# Workspace dirs (host mounts these)
RUN mkdir -p /workspace/ipc/messages /workspace/ipc/tasks /workspace/ipc/routes \
    /workspace/data && \
    chown -R minion:minion /workspace /app

USER minion

ENTRYPOINT ["python", "runner.py"]

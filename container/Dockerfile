FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash git curl ca-certificates apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI (gh) — for gh auth, gh repo create, gh pr create, etc.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
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

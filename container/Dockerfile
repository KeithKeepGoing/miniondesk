FROM python:3.11-slim

LABEL maintainer="MinionDesk"
LABEL description="MinionDesk minion container"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY container/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Runner code
WORKDIR /app
COPY container/runner/ /app/

# Workspace dirs
RUN mkdir -p /workspace/group/output /workspace/group/.ipc /workspace/project

# Run as non-root
RUN useradd -m -u 1000 minion && chown -R minion:minion /app /workspace
USER minion

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "/app/runner.py"]

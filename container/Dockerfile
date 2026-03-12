FROM python:3.9

LABEL maintainer="MinionDesk"
LABEL description="MinionDesk minion container"

# System deps and CJK fonts for PPT/PDF support
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libfreetype6 \
    libpng16-16 \
    zlib1g \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# Pre-install python-pptx (eliminates runtime pip install / network dependency)
RUN pip install --no-cache-dir \
    python-pptx==1.0.2

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
ENV LANG=C.UTF-8

ENTRYPOINT ["python", "/app/runner.py"]

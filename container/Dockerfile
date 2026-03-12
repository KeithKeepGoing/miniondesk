# MinionDesk Agent Container — Production Ready v1.2.13
# Supports: LLM agents, MCP servers, document generation (PPT/PDF/Excel/Word),
#           web scraping, image processing, data science, CJK fonts, non-root security

FROM python:3.11

LABEL maintainer="MinionDesk"
LABEL description="MinionDesk minion container — production-ready with full tool-use support"
LABEL version="1.2.13"

# ── System packages ─────────────────────────────────────────────────────────
# Install everything in a single layer to minimize image size.
# Order: build tools → network tools → image/font libs → document libs →
#        CJK fonts → Node.js → OCR/media → utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # ── Build toolchain (needed by native Python packages) ──
    build-essential \
    gcc \
    g++ \
    make \
    pkg-config \
    libffi-dev \
    libssl-dev \
    # ── Network & VCS tools ──
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    # ── Image / font rendering libraries ──
    libfreetype6 \
    libfontconfig1 \
    libjpeg-dev \
    libpng-dev \
    libwebp-dev \
    libtiff-dev \
    zlib1g-dev \
    # ── PDF / document generation (Cairo + Pango stack) ──
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libxml2-dev \
    libxslt1-dev \
    # ── CJK font support ──
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fonts-noto-cjk \
    # ── OCR (Tesseract with CJK language packs) ──
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    tesseract-ocr-jpn \
    tesseract-ocr-kor \
    # ── Media processing ──
    ffmpeg \
    # ── Shell utilities ──
    jq \
    unzip \
    zip \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# ── Node.js LTS (v20) — required for MCP servers ────────────────────────────
# Install via NodeSource to get a current LTS release rather than the outdated
# Debian package.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version \
    && npm --version

# ── Python packages — pre-installed in image (no runtime pip needed) ─────────
# Split into logical groups; each pip call is one layer so Docker cache is
# reused when only one group changes.

# Document generation
RUN pip install --no-cache-dir \
    python-pptx==1.0.2 \
    reportlab \
    openpyxl \
    python-docx

# Web scraping & HTTP clients
RUN pip install --no-cache-dir \
    requests \
    aiohttp \
    httpx \
    beautifulsoup4 \
    lxml \
    html5lib

# Image processing
RUN pip install --no-cache-dir \
    Pillow \
    opencv-python-headless \
    pytesseract

# Data science & visualisation
RUN pip install --no-cache-dir \
    pandas \
    numpy \
    matplotlib \
    seaborn \
    scipy

# General utilities
RUN pip install --no-cache-dir \
    python-dateutil \
    pytz \
    python-dotenv \
    tenacity \
    tqdm

# ── Project requirements ─────────────────────────────────────────────────────
COPY container/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── App setup ────────────────────────────────────────────────────────────────
WORKDIR /app

# Runner code
COPY container/runner/ /app/

# Workspace directories (writable by the non-root user)
RUN mkdir -p /workspace/group/output /workspace/group/.ipc /workspace/project

# ── Security: run as non-root user ──────────────────────────────────────────
RUN useradd -m -u 1000 minion \
    && chown -R minion:minion /app /workspace

USER minion

# ── Environment ──────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV HOME=/home/minion
# Matplotlib non-interactive backend (no display needed)
ENV MPLBACKEND=Agg

ENTRYPOINT ["python", "/app/runner.py"]

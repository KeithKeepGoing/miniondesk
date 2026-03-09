FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    python-telegram-bot \
    "discord.py" \
    aiohttp \
    pyyaml \
    anthropic \
    google-generativeai \
    openai

COPY host/ ./host/
COPY minions/ ./minions/
COPY workflows/ ./workflows/
COPY run.py ./

CMD ["python", "run.py"]

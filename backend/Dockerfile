FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential redis-server && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
COPY start.sh ./start.sh

RUN sed -i 's/\r$//' ./start.sh && chmod +x ./start.sh && pip install --upgrade pip && pip install ".[dev]"

EXPOSE 8000

CMD ["./start.sh"]

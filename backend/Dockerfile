FROM python:3.12-slim

WORKDIR /app

# netcat-openbsd needed to wait for PostgreSQL before Django starts — prevents race condition on docker compose up
# gcc needed to compile psycopg2 binary extensions
# ansible needed to run provision.yml via ansible-runner — the container acts as the Ansible controller
RUN apt-get update && apt-get install -y \
    netcat-openbsd \
    gcc \
    ansible \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching — dependencies only reinstall when requirements.txt changes
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Daphne serves ASGI — required for Django Channels WebSocket support (Gunicorn only handles WSGI)
EXPOSE 8000
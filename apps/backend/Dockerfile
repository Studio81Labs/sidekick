# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POKER_DATA_DIR=/app/data

WORKDIR /app

RUN addgroup --system poker && adduser --system --ingroup poker poker \
    && printf '%s\n' \
      'deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg check-valid-until=no] https://snapshot.debian.org/archive/debian/20260825T000000Z trixie main' \
      > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gosu=1.17-3+b4 \
    && test "$(dpkg-query -W -f='${Version}' gosu)" = '1.17-3+b4' \
    && rm -rf /var/lib/apt/lists/*

COPY apps/backend/pyproject.toml ./
COPY apps/backend/requirements-prod.txt ./
COPY apps/backend/app ./app
COPY apps/backend/docker-entrypoint.sh /usr/local/bin/backend-entrypoint.sh

RUN python -m pip install --no-cache-dir --require-hashes -r requirements-prod.txt \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && python -m pip check

RUN chmod +x /usr/local/bin/backend-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R poker:poker /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

# The entrypoint starts as root only to repair mounted-volume ownership, then
# immediately execs the application through gosu as the fixed `poker` user.
# nosemgrep: semgrep.dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["/usr/local/bin/backend-entrypoint.sh"]
# nosemgrep: semgrep.dockerfile.security.missing-user.missing-user
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

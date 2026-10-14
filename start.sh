#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo 'Docker is required'; exit 1; }
if ! docker compose version >/dev/null 2>&1; then echo 'Docker Compose v2 is required'; exit 1; fi
if [[ ! -f .env ]]; then
  umask 077
  cp .env.example .env
  key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))' 2>/dev/null || openssl rand -hex 36)"
  printf '\nSENTINEL_API_KEY=%s\n' "$key" >> .env
  echo 'Created private .env and a random API key.'
fi
if [[ "${1:-}" == "--qwen" ]]; then
  sed -i 's/^TTS_PROVIDER=.*/TTS_PROVIDER=qwen/' .env
  docker compose --profile qwen up -d --build
else
  docker compose up -d --build
fi
printf '\nDashboard: http://127.0.0.1:8099\n'
printf 'API key: %s\n' "$(sed -n 's/^SENTINEL_API_KEY=//p' .env)"
echo 'Paste the API key into the dashboard once. Keep it private.'

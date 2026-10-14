#!/usr/bin/env bash
# Deploy the Vigie server from this computer:  bash scripts/deploy.sh [--env]
#   --env   also send the local .env (API keys), over SSH only, readable by the server account alone.
# The code goes to ~/vigie on the server, then Docker rebuilds and restarts the container.
set -euo pipefail
HOST="${VIGIE_HOST:-en2eav0r@64.23.251.10}"
PORT="${VIGIE_SSH_PORT:-5377}"
cd "$(dirname "$0")/.."

python scripts/check_secrets.py --all
tar czf - --exclude=.env --exclude=.git --exclude='data/*.db*' --exclude=data/eval --exclude=data/model_probes.json \
    --exclude=desktop --exclude='__pycache__' --exclude='*.log' --exclude=.pytest_cache \
    Dockerfile .dockerignore compose.yaml Caddyfile requirements.txt .env.example README.md server data/replays \
  | ssh -p "$PORT" "$HOST" 'mkdir -p ~/vigie && tar xzf - -C ~/vigie'

if [[ "${1:-}" == "--env" ]]; then
  ssh -p "$PORT" "$HOST" 'umask 077 && cat > ~/vigie/.env && chmod 600 ~/vigie/.env' < .env
  echo "Sent .env"
fi

ssh -p "$PORT" "$HOST" 'cd ~/vigie && docker compose up -d --build 2>&1 | tail -2 && sleep 8 && curl -fsS http://127.0.0.1:8740/api/health && echo'

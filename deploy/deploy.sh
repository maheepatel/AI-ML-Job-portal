#!/usr/bin/env bash
# Deploy (or update) Gradient on a server you can SSH into. Run from the repo root:
#   bash deploy/deploy.sh <server-ip> <path-to-ssh-private-key> [domain] [ssh-user]
# Domain defaults to <ip-with-dashes>.sslip.io (works with no DNS setup).
set -euo pipefail
IP="$1"; KEY="$2"; DOMAIN="${3:-${1//./-}.sslip.io}"; USER_="${4:-ubuntu}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$USER_@$IP")
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> refreshing the bundled DB snapshot (site starts with today's jobs)"
if [ -f "$ROOT/backend/data/gradient.db" ]; then
  "$ROOT/.venv/Scripts/python" -c "import sqlite3; s=sqlite3.connect(r'$ROOT/backend/data/gradient.db'); d=sqlite3.connect(r'$ROOT/backend/seed/gradient-seed.db'); s.backup(d); d.execute('VACUUM'); d.close()" 2>/dev/null \
    || python -c "import sqlite3; s=sqlite3.connect(r'$ROOT/backend/data/gradient.db'); d=sqlite3.connect(r'$ROOT/backend/seed/gradient-seed.db'); s.backup(d); d.execute('VACUUM'); d.close()"
fi

echo "==> packing the project"
TARBALL="$(mktemp -d)/gradient.tgz"
tar --force-local -czf "$TARBALL" -C "$ROOT" \
  --exclude=.venv --exclude=node_modules --exclude=.git --exclude=frontend/dist \
  --exclude='backend/data/*.db*' --exclude=backend/data/backups --exclude='__pycache__' --exclude='.env*' .
ls -lh "$TARBALL" | awk '{print "    " $5}'

echo "==> server setup (idempotent)"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$ROOT/deploy/server-setup.sh" "$USER_@$IP:/tmp/server-setup.sh"
"${SSH[@]}" "sudo bash /tmp/server-setup.sh"

echo "==> uploading and building (first build takes ~5-10 min)"
scp -i "$KEY" "$TARBALL" "$USER_@$IP:/tmp/gradient.tgz"
"${SSH[@]}" "sudo mkdir -p /opt/gradient && sudo tar -xzf /tmp/gradient.tgz -C /opt/gradient \
  && printf 'SITE_DOMAIN=%s\nVITE_CONTACT_EMAIL=%s\n' '$DOMAIN' '${VITE_CONTACT_EMAIL:-}' | sudo tee /opt/gradient/deploy/.env >/dev/null \
  && cd /opt/gradient/deploy && sudo docker compose -f docker-compose.vps.yml up -d --build"

echo "==> waiting for https://$DOMAIN/api/health"
for i in $(seq 1 60); do
  if curl -fsS --max-time 5 "https://$DOMAIN/api/health" >/dev/null 2>&1; then
    echo "LIVE: https://$DOMAIN"; exit 0
  fi
  sleep 5
done
echo "Not answering on HTTPS yet. Check: ssh in and run 'cd /opt/gradient/deploy && sudo docker compose -f docker-compose.vps.yml logs --tail 50'"
exit 1

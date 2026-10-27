#!/bin/sh
# Volumes mount root-owned: fix ownership as root, then drop to the unprivileged app user.
set -e
if [ "$(id -u)" = "0" ]; then
  for d in /data /app/backend/data; do
    mkdir -p "$d" && chown -R gradient:gradient "$d"
  done
  exec runuser -u gradient -- "$@"
fi
exec "$@"

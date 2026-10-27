#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu server (Oracle Cloud Always Free or any VPS).
# Installs Docker, opens ports 80/443 in the host firewall, adds swap on small machines.
set -euo pipefail

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${SUDO_USER:-ubuntu}" || true

# Oracle's Ubuntu images ship iptables rules that REJECT everything except SSH, even after
# the cloud security list allows 80/443. Insert ACCEPT rules ahead of the REJECT and persist.
if iptables -L INPUT -n | grep -q REJECT; then
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  done
  DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent >/dev/null
  netfilter-persistent save
fi

# 1 GB machines (e.g. the AMD micro shape) need swap to survive a sweep.
if [ "$(free -m | awk '/Mem:/ {print $2}')" -lt 3000 ] && ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Security updates install themselves.
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades >/dev/null
mkdir -p /opt/gradient
echo "server ready"

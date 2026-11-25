#!/usr/bin/env bash
# Runs ON the AWS server (Ubuntu). Safe to run again: the first run asks for settings
# and installs Docker, later runs rebuild and restart the app.
set -euo pipefail

CONFIG="$HOME/findoc.env"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mProblem: %s\033[0m\n' "$*" >&2; exit 1; }

get_setting() { sed -n "s/^$1=//p" "$CONFIG" | tail -n 1; }

# The HTTPS certificate can only be issued once the hostname points here, and
# repeated failures get rate limited, so the hostname is checked before building.
token="$(curl -fsS -m 3 -X PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
public_ip="$(curl -fsS -m 3 -H "X-aws-ec2-metadata-token: $token" \
    http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
lookup() { getent ahostsv4 "$1" | awk '{print $1}' | sort -u | paste -sd ' ' || true; }
points_here() { [ -z "$public_ip" ] || [[ " $(lookup "$1") " == *" $public_ip "* ]]; }

# --- 1. Settings (first run only) --------------------------------------------
# Asked before the slow work, so everything after this runs unattended.
if [ ! -f "$CONFIG" ]; then
    say "First-time settings: two questions, then it runs by itself"
    while true; do
        read -rp "Your hostname, for example myfindoc.duckdns.org: " site
        site="${site#https://}"; site="${site#http://}"; site="${site%%/*}"; site="${site// /}"
        if ! [[ "$site" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
            echo "  That doesn't look like a hostname. Try again."
        elif ! points_here "$site"; then
            echo "  $site points to '$(lookup "$site")', but this server is $public_ip."
            echo "  At duckdns.org set its IP to $public_ip, choose 'update ip', wait a minute, then type it again."
        else
            break
        fi
    done
    groq=""
    while [ -z "$groq" ]; do
        read -rsp "Your Groq API key (paste it; nothing will show, then press Enter): " groq; echo
        groq="${groq//[[:space:]]/}"
        [ -n "$groq" ] || echo "  Nothing was pasted. Try again."
    done

    umask 077
    cat > "$CONFIG" <<EOF
# FinDoc AI settings. After a change, run: bash ~/findoc/deploy/setup.sh
SITE_ADDRESS=$site
GROQ_API_KEY=$groq
GROQ_MODEL=openai/gpt-oss-20b
# Set to false once your accounts exist, so strangers can't sign up.
ALLOW_SIGNUPS=true
# Generated for this server. Don't change these after the first start.
POSTGRES_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET_KEY=$(openssl rand -hex 32)
EOF
fi
ln -sfn "$CONFIG" "$HERE/.env"
SITE="$(get_setting SITE_ADDRESS)"
[ -n "$SITE" ] || fail "SITE_ADDRESS is missing from $CONFIG."
points_here "$SITE" || fail "$SITE points to '$(lookup "$SITE")', but this server is $public_ip.
Set the IP for $SITE to $public_ip, wait a minute, then run this again.
(To use a different hostname, edit SITE_ADDRESS in $CONFIG.)"

# --- 2. Swap -----------------------------------------------------------------
# A t3.small has 2 GB of memory; swap keeps builds and model loading from failing.
if ! sudo swapon --show=NAME --noheadings | grep -q .; then
    say "Adding 4 GB of swap space"
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# --- 3. Docker ---------------------------------------------------------------
if ! sudo docker compose version >/dev/null 2>&1 || ! sudo docker buildx version >/dev/null 2>&1; then
    say "Installing Docker"
    # A brand-new server is still running its own first-boot updates, which hold
    # the package lock, so wait for those rather than fail.
    if command -v cloud-init >/dev/null; then sudo cloud-init status --wait >/dev/null || true; fi
    for attempt in $(seq 1 30); do
        sudo apt-get update -q && break
        [ "$attempt" -lt 30 ] || fail "Could not refresh the package list."
        sleep 10
    done
    sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -q \
        docker.io docker-compose-v2 docker-buildx
    sudo systemctl enable --now docker
fi

# --- 4. Build and start ------------------------------------------------------
say "Building the app (about 10 minutes the first time, quicker after)"
sudo docker compose build

say "Starting the app"
sudo docker compose up -d --remove-orphans

say "Waiting for it to come up"
for _ in $(seq 1 60); do
    if curl -fsS -m 5 "https://$SITE/ready" >/dev/null 2>&1; then
        sudo docker image prune -f >/dev/null
        # Keep recent build layers for quick updates without filling the disk.
        sudo docker buildx prune -f --max-used-space 5gb >/dev/null
        printf '\n\033[1;32mFinDoc AI is live: https://%s\033[0m\n' "$SITE"
        exit 0
    fi
    sleep 5
done

sudo docker compose ps
fail "The app did not answer at https://$SITE within 5 minutes.
See what it says with:  cd ~/findoc/deploy && sudo docker compose logs --tail 50"

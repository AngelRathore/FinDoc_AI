#!/usr/bin/env bash
# Runs ON the AWS server. Saves the database, the uploaded documents, and the
# settings into one file. The file holds private data and keys: keep it safe.
# Redirects below run as you, not root, on purpose.
# shellcheck disable=SC2024
set -euo pipefail
umask 077
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

out="$HOME/findoc-backup.tgz"
work="$(mktemp -d)"
finish() {
    sudo docker compose start api worker >/dev/null
    rm -rf "$work"
}
trap finish EXIT

# Pause the API and worker so the database and the files match each other.
sudo docker compose stop api worker
sudo docker compose exec -T postgres pg_dump -U findoc -Fc findoc > "$work/database.dump"
sudo docker compose run --rm --no-deps -T --entrypoint tar api -C /data/documents -cf - . > "$work/documents.tar"
cp "$HOME/findoc.env" "$work/findoc.env"
tar -C "$work" -czf "$out" database.dump documents.tar findoc.env

echo "Backup saved to $out ($(du -h "$out" | cut -f1))"

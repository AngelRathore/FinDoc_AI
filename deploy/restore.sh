#!/usr/bin/env bash
# Runs ON a server where setup.sh has already finished. Replaces the accounts,
# documents and chats there with the ones in a backup file:
#
#   bash ~/findoc/deploy/restore.sh ~/findoc-backup.tgz
# Redirects below run as you, not root, on purpose.
# shellcheck disable=SC2024
set -euo pipefail
umask 077

backup="${1:?Give the backup file, for example: restore.sh ~/findoc-backup.tgz}"
backup="$(realpath "$backup")"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

read -rp "This replaces ALL data on this server. Type yes to continue: " answer
[ "$answer" = "yes" ] || { echo "Nothing changed."; exit 1; }

work="$(mktemp -d)"
finish() {
    sudo docker compose start api worker >/dev/null
    rm -rf "$work"
}
trap finish EXIT
tar -C "$work" -xzf "$backup" database.dump documents.tar

sudo docker compose stop api worker
sudo docker compose exec -T postgres pg_restore -U findoc -d findoc --clean --if-exists --single-transaction < "$work/database.dump"
sudo docker compose run --rm --no-deps -T --entrypoint sh api \
    -c 'find /data/documents -mindepth 1 -delete && tar -C /data/documents -xf -' < "$work/documents.tar"

echo "Restore finished."

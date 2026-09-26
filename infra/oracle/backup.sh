#!/usr/bin/env bash
# Database only. Keep a separate copy of private PDF objects and the private .env.
set -euo pipefail
umask 077

OPSPILOT_INFRA_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OPSPILOT_BACKUP_DIR="${1:?Usage: backup.sh /absolute/private/backup-directory}"
[[ "$OPSPILOT_BACKUP_DIR" = /* ]] || { echo "Use an absolute backup directory." >&2; exit 1; }
mkdir -p "$OPSPILOT_BACKUP_DIR"
chmod 700 "$OPSPILOT_BACKUP_DIR"
OPSPILOT_BACKUP_TEMP="$(mktemp "$OPSPILOT_BACKUP_DIR/.opspilot.XXXXXX")"
trap 'rm -f -- "$OPSPILOT_BACKUP_TEMP"' EXIT

"$OPSPILOT_INFRA_DIR/ops" exec -T postgres \
  pg_dump -U opspilot_owner -d opspilot --format=custom > "$OPSPILOT_BACKUP_TEMP"
"$OPSPILOT_INFRA_DIR/ops" exec -T postgres \
  pg_restore --list < "$OPSPILOT_BACKUP_TEMP" > /dev/null
OPSPILOT_BACKUP_FILE="$OPSPILOT_BACKUP_DIR/opspilot-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
mv -- "$OPSPILOT_BACKUP_TEMP" "$OPSPILOT_BACKUP_FILE"
echo "Database backup: $OPSPILOT_BACKUP_FILE"
echo "Copy it off the VM; PDF objects and configuration are separate backups."

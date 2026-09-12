#!/bin/sh
set -eu

DATA_DIR="${POKER_DATA_DIR:-/app/data}"
BACKUP_DIR="${POKER_BACKUP_DIR:-}"

mkdir -p "$DATA_DIR"
chown -R poker:poker "$DATA_DIR"
if [ -n "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    chown -R poker:poker "$BACKUP_DIR"
fi

exec gosu poker "$@"

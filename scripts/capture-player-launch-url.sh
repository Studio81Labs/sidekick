#!/bin/sh
set -eu

umask 077
CAPTURE_PATH=${POKER_HERO_PLAYER_LAUNCH_URL_FILE:?Launch URL capture path is required}
LAUNCH_URL=${1:?Player launch URL is required}

case "$CAPTURE_PATH" in
  /*) ;;
  *)
    echo "Launch URL capture path must be absolute" >&2
    exit 2
    ;;
esac

TEMPORARY_PATH="$CAPTURE_PATH.temporary.$$"
trap 'rm -f "$TEMPORARY_PATH"' EXIT HUP INT TERM
printf '%s\n' "$LAUNCH_URL" > "$TEMPORARY_PATH"
chmod 600 "$TEMPORARY_PATH"
mv -f "$TEMPORARY_PATH" "$CAPTURE_PATH"
trap - EXIT HUP INT TERM

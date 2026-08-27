#!/bin/sh
set -eu

if [ -z "${RATER_PASSWORD:-}" ]; then
    echo "RATER_PASSWORD is required (set it in .env or pass -e RATER_PASSWORD=...)." >&2
    exit 1
fi

RATER_USER="${RATER_USER:-rater}"
printf '%s\n' "$RATER_PASSWORD" | htpasswd -ciB /etc/nginx/.htpasswd "$RATER_USER" >/dev/null

export STREAMLIT_SERVER_ADDRESS="${STREAMLIT_SERVER_ADDRESS:-127.0.0.1}"

nginx
exec python /app/run_human_rating.py "$@"

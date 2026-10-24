#!/bin/sh
set -eu
cd /opt/parliament
compose=/opt/parliament/bin/docker-compose
case "${1:-}" in
  government)
    failed=0
    for source in korea opm president-briefings president-speeches president-schedule; do
      "$compose" -f compose.production.yml run --rm worker collect --source "$source" --max-pages 3 --max-records 30 --output "/data/$source" --publish --s3 || failed=1
    done
    exit "$failed"
    ;;
  relay)
    "$compose" -f compose.production.yml run --rm worker relay-outbox --send --limit 100
    ;;
  consume)
    "$compose" -f compose.production.yml run --rm worker consume-versions --consume --output /data/assembly-versions
    ;;
  mail-preview)
    "$compose" -f compose.production.yml run --rm worker mail --output /data/mail-spool --limit 100
    ;;
  mail-send)
    test "${PARLIAMENT_MAIL_DELIVERY_ENABLED:-false}" = true
    "$compose" -f compose.production.yml run --rm worker mail --output /data/mail-spool --limit 10 --send
    ;;
  *) exit 64 ;;
esac

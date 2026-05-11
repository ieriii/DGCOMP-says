#!/usr/bin/env bash
# Push the local seeded data/vocab.sqlite to the VPS.
#
# Run from your laptop, in the repo root:
#
#   ./deploy/sync-db.sh dgcomp@<IP>
#
# Uses rsync over SSH; safe to re-run (transfers only the diff).

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <user@host>" >&2
  exit 1
fi

REMOTE="$1"
LOCAL_DB="data/vocab.sqlite"
REMOTE_DIR="/home/dgcomp/DGCOMP-says/data"

if [[ ! -f "${LOCAL_DB}" ]]; then
  echo "no ${LOCAL_DB} in cwd — run from the repo root" >&2
  exit 1
fi

echo ">>> sanity-checking SQLite integrity locally"
sqlite3 "${LOCAL_DB}" 'PRAGMA quick_check;' | head -1

echo ">>> rsync ${LOCAL_DB} -> ${REMOTE}:${REMOTE_DIR}/"
rsync -avh --progress --partial "${LOCAL_DB}" "${REMOTE}:${REMOTE_DIR}/vocab.sqlite"

echo ">>> verifying on remote"
ssh "${REMOTE}" "sqlite3 ${REMOTE_DIR}/vocab.sqlite 'SELECT COUNT(*) AS vocab, (SELECT COUNT(*) FROM source_documents) AS docs FROM vocab;'"

echo ">>> done"

#!/bin/bash
# SessionStart hook: open the sealed dashboard data for this session.
#
# The repository is public, so docs/*.json and data/**/*.json are committed only
# as ciphertext (*.json.enc). A session that edits data -- the EliseAI daily
# Routine, the packet reconcile, anyone running the pipeline by hand -- needs the
# plaintext working copies on disk BEFORE it starts, or a script that finds no
# history would build from nothing. So this runs synchronously, not async.
#
# It never fails the session: every step is allowed to fail and says why. With
# no DASHBOARD_PASSWORD in the environment it opens nothing and tells Claude not
# to run the pipeline.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0      # local machines: run `python3 scripts/crypto_data.py session-start` by hand
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# The only dependency the unseal needs. Some images ship a system `cryptography`
# whose CFFI backend is missing and that panics on import, so test it, not just
# its presence. Cached with the container after the first run.
if ! python3 -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" 2>/dev/null; then
  pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
    || pip install --quiet --disable-pip-version-check "cryptography>=41" >/dev/null 2>&1 \
    || echo "[sealed data] could not install 'cryptography'; sealed files cannot be opened"
fi

python3 scripts/crypto_data.py session-start || true
exit 0

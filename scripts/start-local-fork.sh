#!/usr/bin/env bash
set -euo pipefail

fork_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$fork_root"
if [[ ! -f dist-server/server/index.js || ! -f dist/index.html ]]; then
  echo 'Build the local fork first: npm run build' >&2
  exit 1
fi
mkdir -p local-state
# Keep the existing 3011 service and its database independent.
export HOST=127.0.0.1
export SERVER_PORT=3012
export NODE_ENV=production
export DATABASE_PATH="$fork_root/local-state/auth.db"
export CLOUDCLI_LOCAL_SERVER_MARKER_PATH="$fork_root/local-state/local-server.json"
export CLOUDCLI_CODEX_RUNTIME_MODE=app-server
# Use the unchanged official client from the verified repository-local setup.
official_source="$fork_root/local-state/codex-reference-0.166.0"
export CLOUDCLI_CODEX_PYTHON="$fork_root/local-state/official-client-venv/bin/python"
export CLOUDCLI_CODEX_BRIDGE_SCRIPT="$fork_root/scripts/codex-official-bridge.py"
if [[ ! -x "$CLOUDCLI_CODEX_PYTHON" || ! -d "$official_source/.git" ]]; then
  echo 'Prepare the official client first: bash scripts/check-official-codex-client.sh' >&2
  exit 1
fi
if [[ "$(git -C "$official_source" rev-parse HEAD)" != 6ff1e1ca3b30fc8b914720681fcf5fe62e95f856 ]]; then
  echo 'Official client revision mismatch.' >&2
  exit 1
fi
git -C "$official_source" diff --quiet HEAD -- sdk/python
export PYTHONPATH="$official_source/sdk/python/src"
# Use the one active tool-managed home; never revive an archived profile.
unset CODEX_HOME
if [[ -z "${CLAUDE_CLI_PATH:-}" && -f /opt/homebrew/lib/node_modules/claude-code-best/dist/cli-node.js ]]; then
  export CLAUDE_CLI_PATH=/opt/homebrew/lib/node_modules/claude-code-best/dist/cli-node.js
fi
exec node dist-server/server/index.js

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
# Use the one active tool-managed home; never revive an archived profile.
unset CODEX_HOME
if [[ -z "${CLAUDE_CLI_PATH:-}" && -f /opt/homebrew/lib/node_modules/claude-code-best/dist/cli-node.js ]]; then
  export CLAUDE_CLI_PATH=/opt/homebrew/lib/node_modules/claude-code-best/dist/cli-node.js
fi
exec node dist-server/server/index.js

#!/usr/bin/env bash
set -euo pipefail

fork_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
revision=6ff1e1ca3b30fc8b914720681fcf5fe62e95f856
checkout="${CODEX_OFFICIAL_SOURCE:-$fork_root/local-state/codex-reference-0.166.0}"
venv="$fork_root/local-state/official-client-venv"
fixtures="$fork_root/experiments/official-codex-client"
codex_executable="$fork_root/node_modules/.bin/codex"

if [[ ! -x "$codex_executable" || "$("$codex_executable" --version)" != 'codex-cli 0.166.0' ]]; then
  echo 'Install this fork’s pinned Codex 0.166.0 dependency first.' >&2
  exit 1
fi
if [[ ! -d "$checkout/.git" ]]; then
  mkdir -p "$(dirname -- "$checkout")"
  git clone --depth 1 --branch rust-v0.166.0 --filter=blob:none --sparse \
    https://github.com/openai/codex.git "$checkout"
  git -C "$checkout" sparse-checkout set sdk/python
fi
if [[ "$(git -C "$checkout" rev-parse HEAD)" != "$revision" ]]; then
  echo 'Official source revision does not match the verified 0.166.0 snapshot.' >&2
  exit 1
fi
git -C "$checkout" diff --quiet HEAD -- sdk/python

if [[ ! -x "$venv/bin/python" ]]; then
  uv venv --python 3.13 "$venv"
fi
uv pip sync --python "$venv/bin/python" "$fixtures/requirements.txt"

# Upstream fixtures launch a real Codex binary with a disposable, unauthenticated
# test home and a loopback model server. They do not use the active ~/.codex home.
unset OPENAI_API_KEY CODEX_API_KEY OPENAI_BASE_URL
export CODEX_EXEC_PATH="$codex_executable"
export PYTHONPATH="$checkout/sdk/python/src"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
exec "$venv/bin/python" -m pytest --override-ini addopts='' -q \
  "$checkout/sdk/python/tests/test_app_server_turn_controls.py" \
  "$checkout/sdk/python/tests/test_turn_subscriptions.py" \
  "$checkout/sdk/python/tests/test_async_client_behavior.py" \
  "$checkout/sdk/python/tests/test_client_rpc_methods.py" \
  "$fixtures/test_transport_eof.py"

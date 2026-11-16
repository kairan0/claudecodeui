# Codex history pagination

## Plan and implementation

Reuse the pinned official app-server protocol and existing IPC bridge. Fetch one
turn summary with `thread/turns/list`, then a bounded page (maximum 100 items)
with `thread/items/list`. No JSONL parser or replacement RPC transport is added.

The browser requests `pagination=cursor`; subsequent pages pass an opaque cursor.
The adapter binds that cursor to the provider thread and, within large turns,
to the original turn ID. Its next-turn continuation survives new live turns.
Other providers and explicit non-paginated readers retain their existing API.

Reuse Codex item normalization, transcript preparation, message reconciliation,
scroll controls and real-time notifications. Native pages advertise
`totalKnown:false`; the browser suppresses a misleading total count. Older-page
requests use cursors rather than offsets or changing transcript totals.

Latest refreshes bridge up to five older pages to reconnect cached history.
If there is still no overlap, show the bounded recent window with its older-page
cursor; do not present disconnected windows as contiguous history. This may
require scrolling back again after a long absence. Rewind invalidates pending
history reads and clears the old continuation. Cursor/thread mismatches fail
explicitly rather than reading a different thread.

## Validation

Read-only diagnostics on a long local diagnostic fork: 10 full turns took
2.17 seconds; one summary plus 20 items took 0.90 seconds. Earlier full-history
hydration exceeded 90 seconds. These are local measurements, not a latency SLA.

Regression coverage includes bounded native calls, item continuation pinned to
its original turn, rejection of another thread's cursor, cursor-based frontend
pagination, and existing rewind/reader-switch tests. Test database paths must
always override the inherited production DATABASE_PATH.

## Fork maintenance

Upstream: https://github.com/siteboon/claudecodeui
Fork: https://github.com/kairan0/claudecodeui

Keep upstream main unchanged. Maintain local features on `codex-enhancements` with
focused commits and this document. Fetch upstream before integrations, run the
provider and client regressions, typecheck, build and lint, then update the fork.
Do not commit local-state, credentials, databases, session files or node_modules.

This feature branch includes steer, Start new turn and the metadata-only rewind
fix. The branch also incorporates upstream 1.37.9, including side questions and
run-settled scheduling, while retaining the FIFO storage and delivery protocol. Publication to GitHub does not deploy the local
production service.

## Upstream 1.37.9 integration validation

Backend suite: 1,192 passed, 4 skipped with test concurrency limited to four.
The unrestricted run encountered a Node test-runner IPC deserialization error;
the affected file passed all 13 tests independently, and the bounded full rerun
passed. Tests use an isolated DATABASE_PATH and clear the host CLAUDE_CLI_PATH
where executable-discovery fixtures require a controlled environment.

Typecheck, production build and lint passed (lint retains existing warnings).
Upstream single-slot queue tests were adapted to independent FIFO entries and
revisioned operations. Claude legacy steering is retained separately from Codex
queue steering; failed persistence of a refused Claude steer restores text/files.

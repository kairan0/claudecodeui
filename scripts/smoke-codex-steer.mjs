// Opt-in live acceptance check: uses the active ~/.codex login and creates ONE
// fresh thread. Never resumes an existing session or copies credentials.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const directory = await mkdtemp(path.join(tmpdir(), 'cloudcli-steer-smoke-'));
process.env.DATABASE_PATH = path.join(directory, 'auth.db');
delete process.env.CODEX_HOME;

const { createCodexAppServerRuntime } = await import('../dist-server/server/modules/providers/list/codex/index.js');
const { CodexSessionsProvider } = await import('../dist-server/server/modules/providers/list/codex/codex-sessions.provider.js');
const { closeConnection } = await import('../dist-server/server/modules/database/index.js');
const sessions = new CodexSessionsProvider();
const sessionId = `steer-smoke-${Date.now()}`;
const model = process.env.CLOUDCLI_SMOKE_MODEL;
const messages = [];
const methods = [];
const observed = [];
let child;
let steerPromise;
let timer;
let steerTimer;
const runtime = createCodexAppServerRuntime({ managerOptions: {
  cwd: directory,
  spawn(executable, args, options) {
    child = spawn(executable, args, options);
    // Observe method names only, never credentials or model traffic.
    const write = child.stdin.write.bind(child.stdin);
    child.stdin.write = (chunk, ...rest) => {
      for (const line of String(chunk).split('\n').filter(Boolean)) {
        try { const frame = JSON.parse(line); if (frame.method) { methods.push(frame.method); console.log(`RPC ${frame.method}`); } } catch {}
      }
      return write(chunk, ...rest);
    };
    return child;
  },
} });

try {
  const result = await Promise.race([
    runtime.run(
      'This is a bounded steering acceptance test. Run the shell command sleep 6 exactly once, then reply exactly BEFORE_STEER. Do not inspect files, change files, use MCP, or access the network.',
      { sessionId, cwd: directory, permissionMode: 'acceptEdits', model, effort: 'low' },
      { send(message) {
        messages.push(message);
        observed.push(message.kind);
        if (['session_created', 'status', 'complete', 'error'].includes(message.kind)) {
          console.log(JSON.stringify({ event: message.kind, status: message.text, exitCode: message.exitCode,
            ...(message.kind === 'error' ? { error: message.content } : {}) }));
        }
        if (message.kind === 'status' && message.text === 'active_turn' && !steerTimer) {
          steerTimer = setTimeout(() => {
            steerPromise = runtime.steer({ sessionId, activeTurnToken: message.activeTurnToken,
              messageId: 'smoke-followup', content: 'Change the final reply: reply exactly AFTER_STEER instead. This instruction applies to the currently running turn.', attachments: [] });
            // Prevent an unhandled rejection while the run is still pending.
            steerPromise.then(() => console.log('Steer acknowledged'), () => console.log('Steer rejected or unconfirmed'));
          }, 1_500);
        }
      }, setSessionId() {} },
      { resolveProviderSessionId: () => null,
        resolveResumeModel: async () => model,
        getProviderModels: async () => ({ OPTIONS: model ? [{ value: model, label: model, effort: { values: [{ value: 'low' }] } }] : [], DEFAULT: model ?? '' }),
        normalizeMessage: sessions.normalizeMessage.bind(sessions),
        isProviderInstalled: async () => true },
    ),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Live steering smoke test timed out after 120 seconds')), 120_000); }),
  ]);
  assert.ok(steerPromise, 'The turn must remain active long enough to steer');
  await steerPromise;
  assert.equal(result.status, 'completed');
  const replies = messages.filter((message) => message.role === 'assistant' && message.kind === 'text');
  assert.equal(String(replies.at(-1)?.content).trim(), 'AFTER_STEER');
  assert.equal(methods.filter((method) => method === 'turn/start').length, 1);
  assert.equal(methods.filter((method) => method === 'turn/steer').length, 1);
  console.log(JSON.stringify({ passed: true, runtime: 'app-server', freshThread: true,
    turnStartCount: 1, turnSteerCount: 1, finalReply: 'AFTER_STEER' }));
} catch (error) {
  console.error(JSON.stringify({ passed: false, methods, observed, error: String(error) }));
  throw error;
} finally {
  clearTimeout(timer);
  clearTimeout(steerTimer);
  child?.kill('SIGTERM');
  if (child && child.exitCode === null) {
    await new Promise((resolve) => {
      const killTimer = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 2_000);
      child.once('exit', () => { clearTimeout(killTimer); resolve(); });
    });
  }
  closeConnection();
  await rm(directory, { recursive: true, force: true });
}

// Invoked by pytest with a disposable home/database and a loopback model.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

import { createCodexAppServerRuntime } from '../../server/modules/providers/list/codex/index.ts';
import { CodexSessionsProvider } from '../../server/modules/providers/list/codex/codex-sessions.provider.ts';
import { closeConnection } from '../../server/modules/database/index.ts';

const messages = [];
const methods = [];
const sessions = new CodexSessionsProvider();
let child;
let activeTurnToken;
let steer;
let providerSessionId;
const runtime = createCodexAppServerRuntime({ managerOptions: {
  executable: process.env.CODEX_EXEC_PATH,
  args: ['app-server', '--listen', 'stdio://', '-c', 'features.instant_interrupt=false'],
  spawn(executable, args, options) {
    child = spawn(executable, args, options);
    const write = child.stdin.write.bind(child.stdin);
    child.stdin.write = (chunk, ...rest) => {
      for (const line of String(chunk).split('\n').filter(Boolean)) {
        const frame = JSON.parse(line);
        if (frame.method) methods.push(frame.method);
      }
      return write(chunk, ...rest);
    };
    return child;
  },
} });

try {
  const result = await runtime.run('Start a steerable turn.', {
    sessionId: 'bridge-fixture', cwd: process.cwd(), model: 'mock-model', permissionMode: 'acceptEdits',
  }, {
    send(message) {
      messages.push(message);
      if (message.kind === 'status' && message.text === 'active_turn') activeTurnToken = message.activeTurnToken;
      if (message.kind === 'text' && message.role === 'assistant' && !steer) {
        steer = runtime.steer({ sessionId: 'bridge-fixture', activeTurnToken,
          messageId: 'bridge-steer', content: 'Use this steering input.', attachments: [] });
        steer.catch(() => {});
      }
    },
    setSessionId(id) { providerSessionId = id; },
  }, {
    resolveProviderSessionId: () => null,
    resolveResumeModel: async () => 'mock-model',
    getProviderModels: async () => ({ OPTIONS: [{ value: 'mock-model', label: 'Mock' }], DEFAULT: 'mock-model' }),
    normalizeMessage: sessions.normalizeMessage.bind(sessions),
    isProviderInstalled: async () => true,
  });
  assert.ok(steer, 'The runtime must expose text while the turn is steerable');
  await steer;
  assert.deepEqual(result, { status: 'completed' });
  assert.equal(messages.filter((m) => m.role === 'assistant' && m.kind === 'text').at(-1)?.content, 'after steer');
  assert.equal(messages.filter((m) => m.kind === 'complete').length, 1);
  assert.equal(methods.filter((m) => m === 'turn/start').length, 1);
  assert.equal(methods.filter((m) => m === 'turn/steer').length, 1);
  const history = await runtime.readThread(providerSessionId);
  assert.match(JSON.stringify(history), /after steer/);
  console.log('CLOUDCLI_RUNTIME_BRIDGE_OK');
} finally {
  if (child && child.exitCode === null) {
    const exited = once(child, 'exit');
    child.stdin.end();
    await exited;
  }
  closeConnection();
}

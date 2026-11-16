import assert from 'node:assert/strict';
import { act, renderHook } from '@testing-library/react';
import { afterEach, test, vi } from 'vitest';
import '@/modules/i18n';
import { useChatComposerState } from '@/modules/chat/hooks/useChatComposerState';
import type { QueueMessageInput, QueuedMessage } from '@/shared/types';

// The upstream single-slot append tests are replaced by FIFO contract tests.
// Revision conflicts, persistence/replay and attachment retry live in queuedMessages.test.tsx.
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });
const project = { projectId: 'p', displayName: 'Project', fullPath: '/tmp/p' };
const session = { id: 's' };
function setup(fail = false) {
  const queued: QueueMessageInput[] = [];
  const sent: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ data: [] }))));
  const view = renderHook(({ model }) => useChatComposerState({
    selectedProject: project,
    selectedSession: session, currentSessionId: 's', provider: 'codex',
    permissionMode: 'default', cyclePermissionMode() {}, resolvePermissionModeForProvider: () => 'default',
    currentProviderModel: model, currentProviderEffort: 'medium', isLoading: true,
    canAbortSession: true, tokenBudget: null, sendMessage: message => { sent.push(message); },
    scrollToBottom() {}, addMessage() {}, setIsUserScrolledUp() {}, setPendingPermissionRequests() {},
    enqueueQueuedMessage: async input => {
      if (fail) throw new Error('offline');
      queued.push(input);
      return { id: String(queued.length), sequence: queued.length, sessionId: 's', ...input,
        attachments: [], revision: 1, status: 'queued', error: null } satisfies QueuedMessage;
    },
  }), { initialProps: { model: 'model-1' } });
  return { view, queued, sent };
}
async function submit(view: ReturnType<typeof setup>['view'], text: string) {
  act(() => view.result.current.setInput(text));
  await act(async () => { await view.result.current.handleSubmit({ preventDefault() {} } as never); });
}
test('follow-ups remain distinct and retain their model at enqueue time', async () => {
  const { view, queued, sent } = setup();
  await submit(view, 'A'); await submit(view, 'B');
  view.rerender({ model: 'model-2' }); await submit(view, 'C');
  assert.deepEqual(queued.map(item => item.content), ['A', 'B', 'C']);
  assert.deepEqual(queued.map(item => item.options.model), ['model-1', 'model-1', 'model-2']);
  assert.equal(view.result.current.input, '');
  assert.deepEqual(sent, []);
});
test('failed durable enqueue preserves the text for retry', async () => {
  const { view, queued } = setup(true);
  await submit(view, 'keep me');
  assert.equal(view.result.current.input, 'keep me');
  assert.deepEqual(queued, []);
});

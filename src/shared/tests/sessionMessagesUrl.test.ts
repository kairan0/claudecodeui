import { expect, test } from 'vitest';
import { sessionMessagesUrl } from '@/shared/api';

test('an empty native cursor still selects cursor pagination', () => {
  const url = new URL(sessionMessagesUrl('session', { cursor: '', limit: 20 }), 'https://example.test');
  expect(url.searchParams.get('pagination')).toBe('cursor');
  expect(url.searchParams.get('limit')).toBe('20');
});

test('opaque cursors round-trip through URL encoding', () => {
  const url = new URL(sessionMessagesUrl('session', { cursor: 'a+/=b', limit: 20 }), 'https://example.test');
  expect(url.searchParams.get('cursor')).toBe('a+/=b');
});

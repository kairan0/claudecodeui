import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import QueuedMessageCard from '@/modules/chat/composer/QueuedMessageCard';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(cleanup);

test('Start new turn invokes its own action instead of steering', () => {
  const start = vi.fn();
  const steer = vi.fn();
  render(<QueuedMessageCard content="Change direction" onEdit={vi.fn()} onDelete={vi.fn()}
    onStartNewTurn={start} onSteer={steer} />);
  fireEvent.click(screen.getByRole('button', { name: 'Start new turn' }));
  expect(start).toHaveBeenCalledOnce();
  expect(steer).not.toHaveBeenCalled();
});

test('a locked message cannot start another turn', () => {
  const start = vi.fn();
  render(<QueuedMessageCard content="Change direction" disabled onEdit={vi.fn()} onDelete={vi.fn()}
    onStartNewTurn={start} />);
  fireEvent.click(screen.getByRole('button', { name: 'Start new turn' }));
  expect(start).not.toHaveBeenCalled();
});

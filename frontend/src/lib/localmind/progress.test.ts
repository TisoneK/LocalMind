import { describe, expect, it } from 'vitest';
import type { TodoItem } from '@/types';
import {
  applyTodoCreated,
  applyTodoUpdated,
  estimateTokens,
  formatLatency,
  formatTokens,
  normalizeTodoEvent,
  isActiveToolStatus,
} from './progress';

const initialTodos: TodoItem[] = [
  { id: 'plan-0', text: 'Understand the request', completed: false, order: 0 },
  { id: 'plan-1', text: 'Run the action', completed: false, order: 1 },
];

describe('streamed progress helpers', () => {
  it('normalizes backend content and status fields', () => {
    expect(normalizeTodoEvent({
      id: 'plan-0',
      content: 'Search the web for the requested story',
      status: 'pending',
      order: 0,
      session_id: 'session-1',
    })).toEqual({
      id: 'plan-0',
      text: 'Search the web for the requested story',
      completed: false,
      status: 'pending',
      order: 0,
      sessionId: 'session-1',
    });
  });

  it('replaces a generic same-ID task with the richer streamed task', () => {
    const updated = applyTodoCreated(initialTodos, {
      id: 'plan-0',
      content: 'Search current news about the requested topic',
      status: 'in_progress',
      order: 0,
    });

    expect(updated).toHaveLength(2);
    expect(updated[0]).toMatchObject({
      id: 'plan-0',
      text: 'Search current news about the requested topic',
      status: 'in_progress',
    });
  });

  it('marks a task complete by stable ID or plan order', () => {
    const byId = applyTodoUpdated(initialTodos, {
      id: 'plan-1',
      status: 'done',
      completed: true,
    });
    expect(byId[1]).toMatchObject({ completed: true, status: 'done' });

    const byOrder = applyTodoUpdated(initialTodos, {
      id: 'missing-id',
      order: 0,
      status: 'in_progress',
    });
    expect(byOrder[0]).toMatchObject({ completed: false, status: 'in_progress' });
  });

  it('treats every backend in-flight status as active', () => {
    expect(isActiveToolStatus('pending')).toBe(true);
    expect(isActiveToolStatus('started')).toBe(true);
    expect(isActiveToolStatus('in_progress')).toBe(true);
    expect(isActiveToolStatus('running')).toBe(true);
    expect(isActiveToolStatus('done')).toBe(false);
    expect(isActiveToolStatus('failed')).toBe(false);
    expect(isActiveToolStatus(undefined)).toBe(false);
  });

  it('estimates completion tokens from streamed response text', () => {
    expect(estimateTokens('')).toBe(0);
    expect(estimateTokens('12345678')).toBe(2);
    expect(estimateTokens('  hello world  ')).toBe(3);
  });
});

describe('formatLatency (B-2026-08-09-4 / ADR-13)', () => {
  it('renders sub-second values as whole milliseconds', () => {
    expect(formatLatency(340)).toBe('340ms');
    expect(formatLatency(0.5)).toBe('1ms');
    expect(formatLatency(999)).toBe('999ms');
  });

  it('switches to one-decimal seconds at 1s and above', () => {
    expect(formatLatency(1000)).toBe('1.0s');
    expect(formatLatency(1200)).toBe('1.2s');
    expect(formatLatency(39900)).toBe('39.9s');
  });

  it('returns an em-dash for missing, zero, or non-finite values', () => {
    expect(formatLatency(0)).toBe('—');
    expect(formatLatency(-5)).toBe('—');
    expect(formatLatency(NaN)).toBe('—');
    expect(formatLatency(Infinity)).toBe('—');
  });

  it('formats minutes and hours (B-2026-08-23-21)', () => {
    expect(formatLatency(60_000)).toBe('1m');
    expect(formatLatency(90_000)).toBe('1m 30s');
    expect(formatLatency(3_600_000)).toBe('1h');
    expect(formatLatency(3_660_000)).toBe('1h 1m');
    expect(formatLatency(7_200_000)).toBe('2h');
  });
});

describe('formatTokens (B-2026-08-23-22)', () => {
  it('renders small counts as-is', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(42)).toBe('42');
    expect(formatTokens(999)).toBe('999');
  });

  it('renders thousands with K suffix', () => {
    expect(formatTokens(1000)).toBe('1.0K');
    expect(formatTokens(128000)).toBe('128K');
    expect(formatTokens(999_999)).toBe('1000K');
  });

  it('renders millions with M suffix', () => {
    expect(formatTokens(1_000_000)).toBe('1.0M');
    expect(formatTokens(1_500_000)).toBe('1.5M');
    expect(formatTokens(100_000_000)).toBe('100M');
  });

  it('returns em-dash for negative and non-finite', () => {
    expect(formatTokens(-1)).toBe('—');
    expect(formatTokens(NaN)).toBe('—');
  });
});

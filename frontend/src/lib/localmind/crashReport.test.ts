import { describe, expect, it } from 'vitest';
import { buildCrashReport } from './crashReport';

describe('buildCrashReport', () => {
  it('names the error, stamps the time and carries both stacks', () => {
    const err = new TypeError("Cannot read properties of undefined (reading 'retryAttempts')");
    const report = buildCrashReport(
      err,
      '\n    at TurnView\n    at StepRow',
      new Date('2026-10-31T12:00:00Z'),
    );
    expect(report).toContain('LocalMind crash report — 2026-10-31T12:00:00.000Z');
    expect(report).toContain("TypeError: Cannot read properties of undefined (reading 'retryAttempts')");
    expect(report).toContain('Stack:');
    expect(report).toContain('Component stack:');
    expect(report).toContain('at TurnView');
  });

  it('omits the sections it does not have', () => {
    const err = new Error('kaboom');
    err.stack = undefined;
    const report = buildCrashReport(err, null, new Date('2026-10-31T12:00:00Z'));
    expect(report).not.toContain('Stack:');
    expect(report).not.toContain('Component stack:');
    expect(report).toContain('Error: kaboom');
  });
});

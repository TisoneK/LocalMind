import { describe, expect, it } from 'vitest';
import { cleanToolFailure, friendlyReplan, friendlyUnmet, stripFallbackErrorText, stripVerificationFooter } from './errorText';

describe('stripFallbackErrorText', () => {
  it('removes the loop fallback when it is the whole reply', () => {
    expect(stripFallbackErrorText('⚠️ The model ran into an issue. Please try again, or switch to a larger model for this task.')).toBe('');
  });

  it('removes the rate-limit fallback', () => {
    expect(stripFallbackErrorText('The model provider rate-limited my request. Please try again in a moment.')).toBe('');
  });

  it('keeps a real partial answer that came before the failure', () => {
    const text = 'Here is what I found so far: the file has 3 rows.\n\n⚠️ The model ran into an issue. Please try again, or switch to a larger model for this task.';
    expect(stripFallbackErrorText(text)).toBe('Here is what I found so far: the file has 3 rows.');
  });

  it('removes the code-aware dead-end fallback (provider named, code verbatim)', () => {
    expect(
      stripFallbackErrorText(
        '⚠️ BankOfAI (promo free models — time-limited) returned `payment_required`; this turn can\'t continue because the failure is not retryable.'
      )
    ).toBe('');
  });

  it('removes the preserved-path no-tool fallback', () => {
    expect(
      stripFallbackErrorText(
        '⚠️ zen returned `payment_required` (not retryable); this turn can\'t continue.'
      )
    ).toBe('');
  });

  it('keeps the honest evidence framing — it is answer content, not fallback', () => {
    const text =
      '⚠️ BankOfAI (promo free models — time-limited) returned `payment_required` while I was writing the answer up, so here is what the evidence already supports, as gathered:\n\nKiambu Town is 25°C and partly sunny.';
    expect(stripFallbackErrorText(text)).toBe(text);
  });

  it('leaves ordinary text alone', () => {
    expect(stripFallbackErrorText('All done.')).toBe('All done.');
  });
});

describe('stripVerificationFooter', () => {
  const body = 'Saved to `/a/top3.txt` (285 bytes, verified on disk).';
  it('removes the criteria line and the Files list but keeps the answer', () => {
    const text = `${body}\n✓ 1/1 criteria met (file exists at /a/top3.txt with\ncontent)\n📁 Files:\n- /a/top3.txt (created, 285 B)`;
    expect(stripVerificationFooter(text)).toBe(body);
  });
  it('leaves ordinary text alone', () => {
    expect(stripVerificationFooter('All 3 criteria are described below.')).toBe('All 3 criteria are described below.');
  });
});

describe('cleanToolFailure', () => {
  it('drops the model-facing header and recovery advice, keeping what the command said', () => {
    const raw = "[Tool 'shell' returned error_type='command_failed']\nCommand failed:\ncat: /x: No such file\n[RECOVERY]: `shell` command failed. Check the error message, fix the command, and retry.";
    expect(cleanToolFailure(raw)).toBe('cat: /x: No such file');
  });
  it('leaves ordinary output alone', () => {
    expect(cleanToolFailure('permission denied')).toBe('permission denied');
  });
});

describe('friendlyUnmet', () => {
  it('rewords loop jargon and keeps real criteria verbatim', () => {
    expect(friendlyUnmet('model narrated an action plan but made zero tool calls')).toMatch(/instead of doing it/);
    expect(friendlyUnmet('narrated a pending action without a tool call')).toMatch(/instead of doing it/);
    expect(friendlyUnmet('file exists at /tmp/a')).toBe('file exists at /tmp/a');
  });
});

describe('friendlyReplan', () => {
  it('turns a replanning warning into a calm course correction', () => {
    expect(friendlyReplan('Replanning — analyze criteria unmet', 'Unmet: it said what it would do instead of doing it')).toEqual({
      label: 'Adjusting the approach',
      detail: 'Because it said what it would do instead of doing it',
    });
  });
  it('leaves other checkpoints alone', () => {
    expect(friendlyReplan('Verified — acceptance gate passed')).toEqual({ label: 'Verified — acceptance gate passed', detail: undefined });
  });
});

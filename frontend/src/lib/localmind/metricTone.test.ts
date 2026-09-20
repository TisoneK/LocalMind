import { describe, expect, it } from 'vitest';
import { cacheTone, latencyTone, speedTone } from './metricTone';

describe('metric tones', () => {
  it('grades latency', () => {
    expect([latencyTone(900), latencyTone(9000), latencyTone(40000), latencyTone(0)]).toEqual(['good', 'warn', 'bad', 'neutral']);
  });
  it('grades speed', () => {
    expect([speedTone(60), speedTone(12), speedTone(4), speedTone(0)]).toEqual(['good', 'warn', 'bad', 'neutral']);
  });
  it('grades cache hits', () => {
    expect([cacheTone(94), cacheTone(40), cacheTone(5), cacheTone(0)]).toEqual(['good', 'warn', 'neutral', 'neutral']);
  });
});

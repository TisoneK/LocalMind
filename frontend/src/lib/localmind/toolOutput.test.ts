import { describe, expect, it } from 'vitest';
import { formatHidden, parseToolOutput, stripTruncation } from './toolOutput';

const SEARCH = `Search results via **DuckDuckGo** (3 results):

1. **Weather today - Kitengela, Kenya**
   https://www.weather-atlas.com/en/kenya/kitengela
   34 minutes ago · Kitengela, Kenya - Current temperature and weather conditions.

2. **Weather in Kitengela, Kenya | Time.now**
   https://time.now/kitengela/weather/
   Check the current weather in Kitengela, Kenya: live temperature, conditions.

3. **Weather Forecast for Kitengela**
   https://weather.com/ke/kajiado/kitengela/postcode/011/today
   Today's and tonight's forecast.`;

const FETCH = `Source: https://wttr.in/Kitengela?format=j1

{
 "current_condition": [
 {
 "temp_C": "18",
 "humidity": "59"
 }
 ]
… [8069 chars truncated] …
 "weatherDesc": [ { "value": "Clear " } ]
}

[... content truncated]`;

describe('stripTruncation', () => {
  it('removes the inline marker and reports how much it stood for', () => {
    const r = stripTruncation('before … [8069 chars truncated] … after');
    expect(r.text).not.toContain('truncated');
    expect(r.text).toContain('before');
    expect(r.text).toContain('after');
    expect(r.hidden).toBe(8069);
    expect(r.cut).toBe(true);
  });

  it('sums several markers and understands thousands separators', () => {
    expect(stripTruncation('a [1,200 chars truncated] b [300 chars truncated] c').hidden).toBe(1500);
  });

  it('drops the tail marker, which carries no count', () => {
    const r = stripTruncation('body\n\n[... content truncated]');
    expect(r.text).toBe('body');
    expect(r.hidden).toBe(0);
    expect(r.cut).toBe(true);
  });

  it('leaves untruncated text alone', () => {
    expect(stripTruncation('plain')).toEqual({ text: 'plain', hidden: 0, cut: false });
  });
});

describe('parseToolOutput', () => {
  it('turns a web search into result entries', () => {
    const v = parseToolOutput({ name: 'web_search', output: SEARCH });
    expect(v.kind).toBe('search');
    if (v.kind !== 'search') return;
    expect(v.provider).toBe('DuckDuckGo');
    expect(v.results).toHaveLength(3);
    expect(v.results[0]).toMatchObject({
      title: 'Weather today - Kitengela, Kenya',
      url: 'https://www.weather-atlas.com/en/kenya/kitengela',
      host: 'weather-atlas.com',
    });
    expect(v.results[1].snippet).toContain('live temperature');
  });

  it('still finds the results when a truncation marker cuts through the list', () => {
    const cut = SEARCH.replace('2. **Weather in Kitengela, Kenya | Time.now**', '… [405 chars truncated] …\n\n2. **Weather in Kitengela, Kenya | Time.now**');
    const v = parseToolOutput({ name: 'web_search', output: cut });
    expect(v.kind).toBe('search');
    if (v.kind !== 'search') return;
    expect(v.results.map((r) => r.host)).toEqual(['weather-atlas.com', 'time.now', 'weather.com']);
    expect(v.hidden).toBe(405);
  });

  it('splits a fetch into its source and body, without the markers', () => {
    const v = parseToolOutput({ name: 'web_fetch', output: FETCH });
    expect(v.kind).toBe('fetch');
    if (v.kind !== 'fetch') return;
    expect(v.source).toBe('https://wttr.in/Kitengela?format=j1');
    expect(v.isJson).toBe(true);
    expect(v.body).not.toContain('truncated');
    expect(v.body).toContain('temp_C');
    expect(v.hidden).toBe(8069);
  });

  it('falls back to plain text for anything else', () => {
    const v = parseToolOutput({ name: 'file_read', output: 'Size: 16 bytes\nLines: 1' });
    expect(v).toEqual({ kind: 'text', body: 'Size: 16 bytes\nLines: 1', hidden: 0 });
  });

  it('does not treat a lookalike header without entries as a search', () => {
    expect(parseToolOutput({ name: 'web_search', output: 'Search results via **X** (0 results):' }).kind).toBe('text');
  });

  it('handles a missing output', () => {
    expect(parseToolOutput({ name: 'shell', output: undefined })).toEqual({ kind: 'text', body: '', hidden: 0 });
  });
});

describe('formatHidden', () => {
  it('formats and pluralises', () => {
    expect(formatHidden(8069)).toBe('8,069 characters');
    expect(formatHidden(1)).toBe('1 character');
  });
});

import { describe, expect, it } from 'vitest';
import { looksLikeJson, prettyJson, tokenizeJson } from './jsonFormat';

describe('looksLikeJson', () => {
  it('recognises objects and arrays, ignoring leading space', () => {
    expect(looksLikeJson('  {"a":1}')).toBe(true);
    expect(looksLikeJson('[1,2]')).toBe(true);
    expect(looksLikeJson('Source: x')).toBe(false);
    expect(looksLikeJson('')).toBe(false);
  });
});

describe('prettyJson', () => {
  it('re-indents valid JSON with two spaces', () => {
    expect(prettyJson('{"a":1,"b":[true,null]}')).toEqual({
      text: '{\n  "a": 1,\n  "b": [\n    true,\n    null\n  ]\n}',
      valid: true,
    });
  });

  it('returns a cut-off document untouched and says it is not valid', () => {
    const cut = '{\n "a": [\n {"b": 1';
    expect(prettyJson(cut)).toEqual({ text: cut, valid: false });
  });
});

describe('tokenizeJson', () => {
  it('classifies keys, strings, numbers and literals', () => {
    const t = tokenizeJson('{"name": "Ada", "age": 36, "ok": true, "x": null}');
    const kinds = (k: string) => t.filter((x) => x.kind === k).map((x) => x.text);
    expect(kinds('key')).toEqual(['"name"', '"age"', '"ok"', '"x"']);
    expect(kinds('string')).toEqual(['"Ada"']);
    expect(kinds('number')).toEqual(['36']);
    expect(kinds('literal')).toEqual(['true', 'null']);
  });

  it('keeps every character, so the highlighted text equals the original', () => {
    const src = '{\n  "a": [1, -2.5e3, "q\\"uote"],\n  "b": {"c": false}\n}';
    expect(tokenizeJson(src).map((x) => x.text).join('')).toBe(src);
  });

  it('does not mistake digits inside a string for numbers', () => {
    const t = tokenizeJson('{"id": "abc123"}');
    expect(t.filter((x) => x.kind === 'number')).toEqual([]);
  });

  it('highlights a cut-off document too', () => {
    const t = tokenizeJson('{"a": [ {"b": 1');
    expect(t.some((x) => x.kind === 'key' && x.text === '"b"')).toBe(true);
  });
});

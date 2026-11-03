import { describe, expect, it } from 'vitest';
import { repairMarkdown } from './markdownRepair';

describe('repairMarkdown — close unclosed emphasis', () => {
  it('closes a lone ** opener at end of line', () => {
    expect(repairMarkdown('Remember **to check the repo')).toBe(
      'Remember **to check the repo**'
    );
  });

  it('closes an unclosed ** at end of input (last line)', () => {
    expect(repairMarkdown('Line one\n**bold text')).toBe(
      'Line one\n**bold text**'
    );
  });

  it('leaves balanced emphasis untouched', () => {
    expect(repairMarkdown('**bold** and *italic* text')).toBe(
      '**bold** and *italic* text'
    );
  });

  it('closes unclosed __ emphasis', () => {
    expect(repairMarkdown('Note the __important part')).toBe(
      'Note the __important part__'
    );
  });

  it('leaves lines with no emphasis untouched', () => {
    expect(repairMarkdown('plain text with no markers')).toBe(
      'plain text with no markers'
    );
  });
});

describe('repairMarkdown — normalize broken bullet lead-ins', () => {
  it('adds space after bullet when emphasis follows (**bold)', () => {
    expect(repairMarkdown('-**bold item**')).toBe('- **bold item**');
  });

  it('adds space after bullet when italic follows (*italic)', () => {
    expect(repairMarkdown('-*italic item*')).toBe('- *italic item*');
  });

  it('normalizes multiple spaces after the marker', () => {
    expect(repairMarkdown('-   spaced item')).toBe('- spaced item');
  });

  it('leaves well-formed bullets untouched', () => {
    expect(repairMarkdown('- normal item\n- another')).toBe(
      '- normal item\n- another'
    );
  });
});

describe('repairMarkdown — full-width table lookalikes (GLM/CJK)', () => {
  it('normalizes a fully full-width table row set into GFM', () => {
    const text = [
      '| Plan ｜ Price ｜ Speed ｜',
      '｜－－－｜－－－｜－－－｜',
      '｜ Plan A ｜ 1,500 ｜ 10 Mbps ｜',
    ].join('\n');
    // Punctuation substitution only — the model's spacing survives, and the
    // (now-ASCII) delimiter row means no second delimiter is inserted.
    expect(repairMarkdown(text)).toBe(
      '| Plan | Price | Speed |\n|---|---|---|\n| Plan A | 1,500 | 10 Mbps |'
    );
  });

  it('normalizes a MIXED row (ASCII outer pipes, one full-width inner pipe)', () => {
    // The 2-column case: a single inner ｜ must still be normalized.
    expect(repairMarkdown('| A ｜ B |')).toBe('| A | B |');
  });

  it('normalizes em/en dashes only inside table rows (spacing preserved)', () => {
    const text = '| X ｜ Y |\n｜－－｜－－｜\nA — B – C － D';
    // Punctuation substitution only — spacing is the model's, and `|--|--|`
    // is valid GFM either way.
    expect(repairMarkdown(text)).toBe(
      '| X | Y |\n|--|--|\nA — B – C － D'
    );
  });

  it('leaves a prose full-width divider (single ｜, no leading pipe) untouched', () => {
    expect(repairMarkdown('上海｜北京')).toBe('上海｜北京');
  });

  it('never touches ｜ inside fenced code or inline code', () => {
    const fenced = '```\n｜ a ｜ b ｜\n```';
    expect(repairMarkdown(fenced)).toBe(fenced);
    const inline = 'use `a ｜ b` here';
    expect(repairMarkdown(inline)).toBe(inline);
  });
});

describe('repairMarkdown — missing GFM delimiter row', () => {
  it('inserts a delimiter under a detected header (3+ uniform rows)', () => {
    const text = [
      '| Plan | Price | Speed |',
      '| Plan A | 1,500 | 10 Mbps |',
      '| Plan B | 2,800 | 40 Mbps |',
    ].join('\n');
    expect(repairMarkdown(text)).toBe(
      '| Plan | Price | Speed |\n| --- | --- | --- |\n| Plan A | 1,500 | 10 Mbps |\n| Plan B | 2,800 | 40 Mbps |'
    );
  });

  it('leaves a well-formed table alone (data rows after a delimiter)', () => {
    const text = [
      '| Plan | Price |',
      '| --- | --- |',
      '| Plan A | 1,500 |',
      '| Plan B | 2,800 |',
    ].join('\n');
    expect(repairMarkdown(text)).toBe(text);
  });

  it('leaves a 2-row run alone (too ambiguous to call a table)', () => {
    const text = '| Plan | Price |\n| Plan A | 1,500 |';
    expect(repairMarkdown(text)).toBe(text);
  });

  it('leaves a ragged run alone (uneven pipe counts)', () => {
    const text = '| Plan | Price |\n| A | B | C |\n| D | E |';
    expect(repairMarkdown(text)).toBe(text);
  });

  it('never inserts inside fenced code', () => {
    const fenced = '```\n| a | b |\n| c | d |\n| e | f |\n```';
    expect(repairMarkdown(fenced)).toBe(fenced);
  });
});

describe('repairMarkdown — protects code', () => {
  it('does not repair inside fenced code blocks', () => {
    const text = 'Here is code:\n```js\nconst x = **not emphasis**;\n```\nDone.';
    expect(repairMarkdown(text)).toBe(text);
  });

  it('does not repair inside inline code', () => {
    const text = 'Use `**this**` literally.';
    expect(repairMarkdown(text)).toBe(text);
  });

  it('still repairs text OUTSIDE code fences', () => {
    const text = 'Remember **this\n```js\nconst a = 1;\n```';
    const out = repairMarkdown(text);
    expect(out).toContain('Remember **this**');
    expect(out).toContain('```js\nconst a = 1;\n```');
  });
});

describe('repairMarkdown — edge cases', () => {
  it('handles empty / whitespace input', () => {
    expect(repairMarkdown('')).toBe('');
    expect(repairMarkdown('  ')).toBe('  ');
  });

  it('single asterisk at line start is a bullet, not emphasis', () => {
    // `* item` is a list — must NOT be "closed" as emphasis.
    expect(repairMarkdown('* item one\n* item two')).toBe(
      '* item one\n* item two'
    );
  });

  it('intraword asterisks are not touched', () => {
    expect(repairMarkdown('foo*bar')).toBe('foo*bar');
  });

  it('intraword DOUBLE markers are literal text, not emphasis (foo**bar)', () => {
    expect(repairMarkdown('foo**bar')).toBe('foo**bar');
    expect(repairMarkdown('a__b')).toBe('a__b');
  });

  it('hrules (***, ___) are valid markdown, never repaired', () => {
    expect(repairMarkdown('***')).toBe('***');
    expect(repairMarkdown('___')).toBe('___');
    expect(repairMarkdown('* * *')).toBe('* * *');
  });

  it('trailing marker on a word is a filename/typo, not emphasis', () => {
    expect(repairMarkdown('see my_file')).toBe('see my_file');
    expect(repairMarkdown('path/to/file_')).toBe('path/to/file_');
  });
});

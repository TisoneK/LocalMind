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

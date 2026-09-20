import { describe, expect, it } from 'vitest';
import { buildChatFiles, filterChatFiles } from './sessionFiles';
import type { SessionFileEntry } from '@/types';

const f = (relPath: string, over: Partial<SessionFileEntry> = {}): SessionFileEntry => ({
  name: relPath.split('/').pop() as string,
  type: 'file',
  path: `/ws/${relPath}`,
  relPath,
  size: 10,
  modified: '2026-09-19T10:00:00',
  ...over,
});

describe('buildChatFiles', () => {
  it('keeps files only and hides staging and dot folders', () => {
    const rows = buildChatFiles([
      f('notes.txt'),
      f('.tmp/notes.txt'),
      f('src/.cache/x.bin'),
      f('sub', { type: 'folder' }),
    ]);
    expect(rows.map((r) => r.path)).toEqual(['/ws/notes.txt']);
  });

  it('splits the folder from the name', () => {
    const [row] = buildChatFiles([f('src/app/main.ts')]);
    expect(row).toMatchObject({ name: 'main.ts', dir: 'src/app' });
    expect(buildChatFiles([f('a.txt')])[0].dir).toBe('');
  });

  it('sorts newest first, ties by path, missing dates last', () => {
    const rows = buildChatFiles([
      f('old.txt', { modified: '2026-09-18T09:00:00' }),
      f('new.txt', { modified: '2026-09-19T12:00:00' }),
      f('nodate.txt', { modified: '' }),
      f('b.txt', { modified: '2026-09-19T12:00:00' }),
    ]);
    expect(rows.map((r) => r.name)).toEqual(['b.txt', 'new.txt', 'old.txt', 'nodate.txt']);
  });

  it('attaches diff counts by path', () => {
    const rows = buildChatFiles([f('a.txt'), f('b.txt')], {
      '/ws/a.txt': {
        hunks: [{ filePath: '/ws/a.txt', oldStart: 0, oldLines: 0, newStart: 1, newLines: 2, lines: [
          { type: 'added', content: 'x' }, { type: 'added', content: 'y' }, { type: 'removed', content: 'z' },
        ] }],
      } as never,
    });
    expect(rows.find((r) => r.name === 'a.txt')?.change).toEqual({ additions: 2, deletions: 1 });
    expect(rows.find((r) => r.name === 'b.txt')?.change).toBeNull();
  });
});

describe('filterChatFiles', () => {
  const rows = buildChatFiles([f('notes.txt'), f('src/app/main.ts')]);
  it('matches name or folder, case-insensitively', () => {
    expect(filterChatFiles(rows, 'NOTES').map((r) => r.name)).toEqual(['notes.txt']);
    expect(filterChatFiles(rows, 'app').map((r) => r.name)).toEqual(['main.ts']);
  });
  it('returns everything for a blank query', () => {
    expect(filterChatFiles(rows, '  ')).toHaveLength(2);
  });

  it('hides the edit tool\'s .bak backup while the original is there', () => {
    const rows = buildChatFiles([f('shopping.txt'), f('shopping.txt.bak'), f('orphan.bak')]);
    expect(rows.map((r) => r.name).sort()).toEqual(['orphan.bak', 'shopping.txt']);
  });
});


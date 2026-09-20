import { describe, expect, it } from 'vitest';
import { toolIconMeta } from './toolIconMeta';

describe('toolIconMeta', () => {
  it('gives each kind of work its own colour', () => {
    expect(toolIconMeta('web_search')).toMatchObject({ kind: 'web', tone: 'text-brand-blue' });
    expect(toolIconMeta('web_fetch').kind).toBe('web');
    expect(toolIconMeta('file_read')).toMatchObject({ kind: 'read', tone: 'text-cyan-300' });
    expect(toolIconMeta('system_search').kind).toBe('search');
    expect(toolIconMeta('file_write')).toMatchObject({ kind: 'write', tone: 'text-brand-amber' });
    expect(toolIconMeta('edit_file').kind).toBe('write');
    expect(toolIconMeta('shell')).toMatchObject({ kind: 'command', tone: 'text-brand-green' });
    expect(toolIconMeta('memory_op')).toMatchObject({ kind: 'memory', tone: 'text-brand-purple' });
  });

  it('falls back to a neutral tool icon for anything unknown', () => {
    expect(toolIconMeta('brand_new_tool')).toMatchObject({ kind: 'tool', tone: 'text-brand-green-muted' });
    expect(toolIconMeta(undefined).kind).toBe('tool');
  });
});

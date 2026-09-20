/** ShortcutsList — the keys the app answers to, in one place. */

const GROUPS: { title: string; items: [string, string][] }[] = [
  {
    title: 'Anywhere',
    items: [
      ['⌘K / Ctrl+K', 'Search chats and run actions'],
      ['⌘N', 'New chat'],
      ['Esc', 'Stop the agent'],
    ],
  },
  {
    title: 'Message box',
    items: [
      ['Enter', 'Send'],
      ['Shift+Enter', 'New line'],
      ['Esc', 'Cancel editing your last message'],
    ],
  },
  {
    title: 'Terminal',
    items: [
      ['↑ / ↓', 'Command history'],
      ['Tab', 'Autocomplete'],
      ['Ctrl+L', 'Clear the screen'],
      ['Ctrl+C', 'Cancel the running command'],
    ],
  },
];

export function ShortcutsList() {
  return (
    <div className="space-y-5" data-testid="shortcuts">
      {GROUPS.map((g) => (
        <div key={g.title}>
          <div className="mb-1.5 text-[11px] uppercase tracking-wider text-brand-green-faint">{g.title}</div>
          <div className="divide-y divide-brand-border/50 rounded-lg border border-brand-border">
            {g.items.map(([keys, what]) => (
              <div key={keys + what} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="text-brand-green-soft">{what}</span>
                <kbd className="rounded border border-brand-border bg-brand-bg-rail px-1.5 py-px font-mono text-[11px] text-brand-green-soft">{keys}</kbd>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

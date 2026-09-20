/**
 * CommandPalette — ⌘K / Ctrl+K: jump to any chat, start a new one, or move around the workspace
 * without reaching for the mouse. The list is built from what the app already knows (sessions,
 * the streaming state), so it never offers a command that cannot run.
 */

import { useEffect, useMemo, useState } from 'react';
import { localmindClient } from '@/lib/localmind/client';
import { FolderOpen, MessageSquare, PanelRight, Plus, Square, Terminal, Brain, Bot } from 'lucide-react';
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';
import type { Session } from '@/types';

interface CommandPaletteProps {
  sessions: Session[];
  currentSessionId: string | null;
  isStreaming: boolean;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onAbort: () => void;
  onToggleRightPanel: () => void;
}

const ITEM = 'gap-2 text-[12px] text-brand-green-soft data-[selected=true]:bg-brand-green/10 data-[selected=true]:text-brand-green';

/** True for the ⌘K / Ctrl+K chord. */
export function isPaletteShortcut(e: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey'>): boolean {
  return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
}

export function CommandPalette({
  sessions,
  currentSessionId,
  isStreaming,
  onSelectSession,
  onNewChat,
  onAbort,
  onToggleRightPanel,
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<{ id: string; title: string; snippet: string }[]>([]);

  // Search what was SAID in your chats, not just their titles (debounced, server-side).
  useEffect(() => {
    const q = query.trim();
    if (!open || q.length < 2) {
      setFound([]);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      localmindClient
        .searchChats(q)
        .then((r) => live && setFound(r))
        .catch(() => live && setFound([]));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [query, open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isPaletteShortcut(e)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const run = (fn: () => void) => () => {
    setOpen(false);
    // Let the dialog release focus first, so a command that focuses something keeps it.
    setTimeout(fn, 0);
  };
  const fire = (name: string) => () => window.dispatchEvent(new CustomEvent(name));

  const recent = useMemo(() => sessions.slice(0, 30), [sessions]);

  return (
    <CommandDialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery('');
      }}
      title="Command palette"
      description="Search chats and actions"
      showCloseButton={false}
      className="max-w-lg border border-brand-border bg-brand-bg-base"
    >
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Search chats and actions…"
        className="h-10 border-0 bg-transparent text-[12px] text-brand-green-soft outline-none ring-0 focus:ring-0 focus-visible:ring-0 placeholder:text-brand-green-muted"
      />
      <CommandList className="max-h-[50vh] bg-brand-bg-base">
        {found.length === 0 && (
          <CommandEmpty className="py-6 text-center text-[11px] text-brand-green-muted">Nothing matches.</CommandEmpty>
        )}
        <CommandGroup heading="Actions">
          <CommandItem className={ITEM} onSelect={run(onNewChat)}>
            <Plus className="h-3.5 w-3.5" /> New chat <CommandShortcut>⌘N</CommandShortcut>
          </CommandItem>
          {isStreaming && (
            <CommandItem className={ITEM} onSelect={run(onAbort)}>
              <Square className="h-3.5 w-3.5" /> Stop the agent <CommandShortcut>Esc</CommandShortcut>
            </CommandItem>
          )}
          <CommandItem className={ITEM} onSelect={run(onToggleRightPanel)}>
            <PanelRight className="h-3.5 w-3.5" /> Toggle the side panel
          </CommandItem>
          <CommandItem className={ITEM} onSelect={run(fire('localmind:focus-agents'))}>
            <Bot className="h-3.5 w-3.5" /> Show agents, plan and tasks
          </CommandItem>
          <CommandItem className={ITEM} onSelect={run(fire('localmind:focus-terminal'))}>
            <Terminal className="h-3.5 w-3.5" /> Show the terminal
          </CommandItem>
          <CommandItem className={ITEM} onSelect={run(fire('localmind:focus-memory'))}>
            <Brain className="h-3.5 w-3.5" /> Show memory
          </CommandItem>
          <CommandItem className={ITEM} onSelect={run(fire('localmind:focus-files'))}>
            <FolderOpen className="h-3.5 w-3.5" /> Show this chat's files
          </CommandItem>
        </CommandGroup>
        {found.length > 0 && (
          <CommandGroup heading="In your chats" forceMount>
            {found.map((f) => (
              <CommandItem
                key={`hit-${f.id}`}
                value={`hit ${f.id}`}
                forceMount
                className={`${ITEM} items-start`}
                onSelect={run(() => onSelectSession(f.id))}
              >
                <MessageSquare className="mt-0.5 h-3.5 w-3.5" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{f.title || 'Untitled chat'}</span>
                  <span className="block truncate text-[10.5px] text-brand-green-muted">{f.snippet}</span>
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {recent.length > 0 && (
          <CommandGroup heading="Chats">
            {recent.map((s) => (
              <CommandItem
                key={s.id}
                value={s.id}
                keywords={[s.title || 'Untitled chat']}
                className={ITEM}
                onSelect={run(() => onSelectSession(s.id))}
              >
                <MessageSquare className="h-3.5 w-3.5" />
                <span className="min-w-0 flex-1 truncate">{s.title || 'Untitled chat'}</span>
                {s.id === currentSessionId && <span className="text-[10px] text-brand-green-muted">open</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}

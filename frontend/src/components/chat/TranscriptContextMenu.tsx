'use client';

import React, { useCallback, useState } from 'react';
import { Copy, FileText, TextSelect } from 'lucide-react';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';

/**
 * Marks the root element of a chat message inside the transcript so the
 * right-click capture can attribute the menu to a specific message.
 */
export const MESSAGE_CONTENT_ATTR = 'data-message-content-id';

interface TranscriptContextMenuProps {
  /** The transcript DOM. Rendered inside the right-click trigger. */
  children: React.ReactNode;
  /** Resolve a message's full text for "Copy message" (by its id). */
  getMessageText?: (messageId: string) => string | undefined;
  /** Select the whole transcript (usually the messages container). */
  onSelectAll?: () => void;
}

interface TranscriptSnapshot {
  /** Document selection captured at menu-open time. */
  selection: string;
  /** Id of the message under the pointer, or null when off-message. */
  messageId: string | null;
}

/**
 * Right-click menu for the chat transcript: Copy (the selection), Copy
 * message (the full text of the right-clicked message), and Select all
 * (scoped to the transcript). The selection text is captured the moment
 * the menu opens — interacting with menu items must not depend on the
 * document selection still being alive — and Copy is disabled when
 * nothing is selected, like a native menu.
 */
export function TranscriptContextMenu({ children, getMessageText, onSelectAll }: TranscriptContextMenuProps) {
  const [snapshot, setSnapshot] = useState<TranscriptSnapshot>({ selection: '', messageId: null });

  // Runs alongside the trigger's own open handler (Radix composes child
  // handlers first), so the message id is known before the menu renders.
  const handleMessageTarget = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement | null;
    const el = target?.closest?.(`[${MESSAGE_CONTENT_ATTR}]`);
    setSnapshot((prev) => ({ ...prev, messageId: el?.getAttribute(MESSAGE_CONTENT_ATTR) ?? null }));
  }, []);

  const handleOpenChange = useCallback((open: boolean) => {
    if (!open) return;
    setSnapshot((prev) => ({ ...prev, selection: window.getSelection?.()?.toString() ?? '' }));
  }, []);

  const copySelection = useCallback(async () => {
    if (!snapshot.selection) return;
    try {
      await navigator.clipboard.writeText(snapshot.selection);
    } catch {
      // Clipboard unavailable (e.g. non-secure context) — stay quiet.
    }
  }, [snapshot.selection]);

  const copyMessage = useCallback(async () => {
    const text = snapshot.messageId ? getMessageText?.(snapshot.messageId) : undefined;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard unavailable — stay quiet.
    }
  }, [snapshot.messageId, getMessageText]);

  const messageText = snapshot.messageId ? getMessageText?.(snapshot.messageId) : undefined;
  const hasSelection = snapshot.selection.length > 0;

  return (
    <ContextMenu onOpenChange={handleOpenChange}>
      <ContextMenuTrigger asChild onContextMenu={handleMessageTarget}>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem
          data-testid="ctx-copy-selection"
          disabled={!hasSelection}
          onSelect={copySelection}
        >
          <Copy />
          Copy
        </ContextMenuItem>
        {messageText ? (
          <ContextMenuItem
            data-testid="ctx-copy-message"
            onSelect={copyMessage}
          >
            <FileText />
            Copy message
          </ContextMenuItem>
        ) : null}
        {onSelectAll ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem
              data-testid="ctx-select-all"
              onSelect={onSelectAll}
            >
              <TextSelect />
              Select all
            </ContextMenuItem>
          </>
        ) : null}
      </ContextMenuContent>
    </ContextMenu>
  );
}

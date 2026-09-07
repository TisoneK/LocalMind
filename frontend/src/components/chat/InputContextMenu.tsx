'use client';

import React, { useCallback, useState } from 'react';
import { ClipboardPaste, Copy, ScanText, Scissors } from 'lucide-react';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';

interface InputContextMenuProps {
  /** The editable element — becomes the right-click trigger. */
  children: React.ReactNode;
  /** Ref to the same element (shared with the owner for typing/focus). */
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  /** Current controlled value, used to compute cut/paste results. */
  value: string;
  /** Controlled-state setter; Cut and Paste deliver their edit here. */
  onChange: (next: string) => void;
}

/**
 * Right-click edit menu for the message input: Cut / Copy / Paste /
 * Select all, mirroring a native text-field menu. Selection bounds are
 * read from the textarea at action time (they survive the menu taking
 * focus in Chromium), while the disabled flags come from a snapshot
 * taken when the menu opens. Cut/Paste apply their edit through the
 * owner's controlled state, so the input stays the single source of
 * truth; the caret is restored once the new value lands.
 */
export function InputContextMenu({ children, textareaRef, value, onChange }: InputContextMenuProps) {
  const [snapshot, setSnapshot] = useState({ hasSelection: false, hasValue: false });

  const handleOpenChange = useCallback((open: boolean) => {
    if (!open) return;
    const el = textareaRef.current;
    if (!el) return;
    setSnapshot({
      hasSelection: el.selectionEnd > el.selectionStart,
      hasValue: el.value.length > 0,
    });
  }, [textareaRef]);

  const restoreCaret = useCallback((caret: number) => {
    const el = textareaRef.current;
    if (!el) return;
    // The controlled value lands on the next render; place the caret
    // where the edit finished once it does.
    requestAnimationFrame(() => {
      el.focus();
      try {
        el.setSelectionRange(caret, caret);
      } catch {
        // Element detached between frames — nothing to restore.
      }
    });
  }, [textareaRef]);

  const handleCut = useCallback(async () => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    if (end <= start) return;
    try {
      // Copy first — if the clipboard is unavailable, leave the text in
      // place rather than "cutting" it into nothing.
      await navigator.clipboard.writeText(value.slice(start, end));
    } catch {
      return;
    }
    onChange(value.slice(0, start) + value.slice(end));
    restoreCaret(start);
  }, [textareaRef, value, onChange, restoreCaret]);

  const handleCopy = useCallback(async () => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    if (end <= start) return;
    try {
      await navigator.clipboard.writeText(value.slice(start, end));
    } catch {
      // Clipboard unavailable — stay quiet.
    }
  }, [textareaRef, value]);

  const handlePaste = useCallback(async () => {
    let text = '';
    try {
      text = await navigator.clipboard.readText();
    } catch {
      return; // Clipboard read denied or unavailable — nothing to insert.
    }
    if (!text) return;
    const el = textareaRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onChange(value.slice(0, start) + text + value.slice(end));
    restoreCaret(start + text.length);
  }, [textareaRef, value, onChange, restoreCaret]);

  const handleSelectAll = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(0, el.value.length);
  }, [textareaRef]);

  return (
    <ContextMenu onOpenChange={handleOpenChange}>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem data-testid="ctx-cut" disabled={!snapshot.hasSelection} onSelect={handleCut}>
          <Scissors />
          Cut
        </ContextMenuItem>
        <ContextMenuItem data-testid="ctx-copy" disabled={!snapshot.hasSelection} onSelect={handleCopy}>
          <Copy />
          Copy
        </ContextMenuItem>
        <ContextMenuItem data-testid="ctx-paste" onSelect={handlePaste}>
          <ClipboardPaste />
          Paste
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem data-testid="ctx-select-all" disabled={!snapshot.hasValue} onSelect={handleSelectAll}>
          <ScanText />
          Select all
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

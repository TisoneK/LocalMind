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

interface EditTarget {
  start: number;
  end: number;
  value: string;
}

/**
 * Right-click edit menu for the message input: Cut / Copy / Paste /
 * Select all, mirroring a native text-field menu. The selection bounds
 * are captured once when the menu opens and every action applies to that
 * captured range — re-reading the caret at click time is unreliable,
 * because opening the menu and returning focus moves it. Cut/Paste apply
 * their edit through the owner's controlled state, so the input stays
 * the single source of truth; the caret is restored onto the captured
 * position once the new value lands.
 */
export function InputContextMenu({ children, textareaRef, value, onChange }: InputContextMenuProps) {
  // Captured at open; also drives the disabled flags.
  const [target, setTarget] = useState<EditTarget | null>(null);
  const hasSelection = target ? target.end > target.start : false;

  const captureTarget = useCallback((): EditTarget | null => {
    const el = textareaRef.current;
    if (!el) return null;
    return { start: el.selectionStart, end: el.selectionEnd, value: el.value };
  }, [textareaRef]);

  const handleOpenChange = useCallback((open: boolean) => {
    if (!open) return;
    setTarget(captureTarget());
  }, [captureTarget]);

  const restoreCaret = useCallback((caret: number) => {
    const el = textareaRef.current;
    if (!el) return;
    const place = () => {
      el.focus();
      try {
        el.setSelectionRange(caret, caret);
      } catch {
        // Element detached between frames — nothing to restore.
      }
    };
    // The controlled value lands on the next render. A timer alone can
    // land before React's commit; rAF alone never fires in a hidden or
    // throttled document — schedule both, they are idempotent.
    setTimeout(place, 0);
    requestAnimationFrame(place);
  }, [textareaRef]);

  const handleCut = useCallback(async () => {
    if (!target || target.end <= target.start) return;
    try {
      // Copy first — if the clipboard is unavailable, leave the text in
      // place rather than "cutting" it into nothing.
      await navigator.clipboard.writeText(target.value.slice(target.start, target.end));
    } catch {
      return;
    }
    onChange(target.value.slice(0, target.start) + target.value.slice(target.end));
    restoreCaret(target.start);
  }, [target, onChange, restoreCaret]);

  const handleCopy = useCallback(async () => {
    if (!target || target.end <= target.start) return;
    try {
      await navigator.clipboard.writeText(target.value.slice(target.start, target.end));
    } catch {
      // Clipboard unavailable — stay quiet.
    }
  }, [target]);

  const handlePaste = useCallback(async () => {
    let text = '';
    try {
      text = await navigator.clipboard.readText();
    } catch {
      return; // Clipboard read denied or unavailable — nothing to insert.
    }
    if (!text) return;
    // The target captured at menu-open is authoritative, but if the user
    // re-opened the menu elsewhere mid-flight, prefer the live caret.
    const live = captureTarget();
    const base = live && live.value === target?.value ? live : target;
    const start = base?.start ?? value.length;
    const end = base?.end ?? value.length;
    onChange(value.slice(0, start) + text + value.slice(end));
    restoreCaret(start + text.length);
  }, [captureTarget, target, value, onChange, restoreCaret]);

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
        <ContextMenuItem data-testid="ctx-cut" disabled={!hasSelection} onSelect={handleCut}>
          <Scissors />
          Cut
        </ContextMenuItem>
        <ContextMenuItem data-testid="ctx-copy" disabled={!hasSelection} onSelect={handleCopy}>
          <Copy />
          Copy
        </ContextMenuItem>
        <ContextMenuItem data-testid="ctx-paste" onSelect={handlePaste}>
          <ClipboardPaste />
          Paste
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem
          data-testid="ctx-select-all"
          disabled={!target || target.value.length === 0}
          onSelect={handleSelectAll}
        >
          <ScanText />
          Select all
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

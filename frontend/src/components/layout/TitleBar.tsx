'use client';

/**
 * ADR-34 B-11: Deliberate LocalMind title-bar chrome.
 *
 * Replaces the default OS title bar with a minimal, draggable bar that
 * preserves native window controls on all platforms:
 * - macOS: `titleBarStyle: 'hiddenInset'` keeps the traffic lights; this
 *   bar renders in the inset space and is fully draggable.
 * - Windows/Linux: `frame: true` is kept for now (native controls remain);
 *   this bar still renders as a header strip but without custom min/max/close
 *   buttons — the OS frame provides them.
 * - Browser fallback: `window.electronAPI` is undefined, so no window-control
 *   buttons render. The bar still serves as a draggable header inside the
 *   web app.
 *
 * The entire bar is a drag region (`-webkit-app-region: drag`) except for
 * interactive elements, which are marked `no-drag`.
 */

import { Minus, Square, X } from 'lucide-react';

interface TitleBarProps {
  /** App version pill text, e.g. "v0.5.16". */
  version?: string;
}

export function TitleBar({ version }: TitleBarProps) {
  const hasElectron = typeof window !== 'undefined' && Boolean(window.electronAPI);

  const handleMinimize = () => window.electronAPI?.minimizeWindow();
  const handleMaximize = () => window.electronAPI?.maximizeWindow();
  const handleClose = () => window.electronAPI?.closeWindow();

  return (
    <div
      className="flex items-center justify-between h-8 px-3 bg-brand-bg-base border-b border-brand-border select-none"
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
    >
      {/* Left: wordmark + version */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold text-brand-green-soft tracking-wide">
          LocalMind
        </span>
        {version && (
          <span className="text-[9px] text-brand-green-faint font-mono">
            {version}
          </span>
        )}
      </div>

      {/* Center: spacer (draggable) — nothing rendered */}
      <div className="flex-1" />

      {/* Right: window controls (Electron only) */}
      {hasElectron && (
        <div
          className="flex items-center gap-1"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <button
            onClick={handleMinimize}
            className="p-1 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title="Minimize"
            aria-label="Minimize window"
          >
            <Minus className="h-3 w-3" />
          </button>
          <button
            onClick={handleMaximize}
            className="p-1 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title="Maximize"
            aria-label="Maximize or restore window"
          >
            <Square className="h-3 w-3" />
          </button>
          <button
            onClick={handleClose}
            className="p-1 rounded hover:bg-brand-red/20 text-brand-green-muted hover:text-brand-red transition-colors"
            title="Close"
            aria-label="Close window"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}

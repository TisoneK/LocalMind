'use client';

/**
 * ADR-34 B-11 + Session 234: deliberate LocalMind title-bar chrome.
 *
 * Replaces the default OS title bar with a minimal, draggable bar:
 * - macOS: `titleBarStyle: 'hiddenInset'` keeps the native traffic lights
 *   and removes the title text. The system provides window controls, so the
 *   custom min/max/close buttons do NOT render here.
 * - Windows: the window is fully frameless (`frame: false`), so the custom
 *   min/max/close buttons are the ONLY window controls. The icon tracks the
 *   real maximize state via IPC, and double-clicking the drag region toggles
 *   maximize (native Windows title-bar behavior).
 * - Linux: the default frame is kept (native controls), so the custom
 *   buttons stay hidden, same as macOS.
 * - Browser fallback: `window.electronAPI` is undefined, so no window-control
 *   buttons render. The bar still serves as a draggable header inside the
 *   web app.
 *
 * The entire bar is a drag region (`-webkit-app-region: drag`) except for
 * interactive elements, which are marked `no-drag`.
 */

import { Minus, Square, Copy, X } from 'lucide-react';
import { useEffect, useState } from 'react';

interface TitleBarProps {
  /** App version pill text, e.g. "v0.5.16". */
  version?: string;
}

export function TitleBar({ version }: TitleBarProps) {
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
  const hasElectron = Boolean(api);
  // Custom window controls only make sense on frameless Windows — macOS
  // (hiddenInset) and Linux (default frame) keep native controls.
  const isWindows = api?.platform === 'win32';
  const isMac = api?.platform === 'darwin';
  const showCustomControls = hasElectron && isWindows;

  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    if (!hasElectron) return;
    api?.isMaximized().then(setIsMaximized).catch(() => {});
    const unsubscribe = api?.onMaximizeChange(setIsMaximized);
    return () => unsubscribe?.();
  }, [hasElectron, api]);

  const handleMinimize = () => api?.minimizeWindow();
  const handleMaximize = () => api?.maximizeWindow();
  const handleClose = () => api?.closeWindow();

  return (
    <div
      data-testid="title-bar"
      data-platform={api?.platform ?? 'browser'}
      className={`flex items-center justify-between h-8 px-3 ${isMac ? 'pl-[84px]' : ''} overflow-hidden bg-brand-bg-panel border-b border-brand-border select-none`}
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      onDoubleClick={showCustomControls ? handleMaximize : undefined}
      title={showCustomControls ? 'Double-click to maximize/restore' : undefined}
    >
      {/* Left: wordmark + version */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[11px] font-semibold text-brand-green-soft tracking-wide truncate">
          LocalMind
        </span>
        {version && (
          <span className="text-[9px] text-brand-green-faint font-mono shrink-0">
            {version}
          </span>
        )}
      </div>

      {/* Center: spacer (draggable) — nothing rendered */}
      <div className="flex-1" />

      {/* Right: window controls (frameless Windows only) */}
      {showCustomControls && (
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
            title={isMaximized ? 'Restore' : 'Maximize'}
            aria-label={isMaximized ? 'Restore window' : 'Maximize window'}
          >
            {isMaximized ? (
              <Copy className="h-3 w-3" />
            ) : (
              <Square className="h-3 w-3" />
            )}
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

/**
 * AppErrorBoundary — a render crash must never leave a blank window.
 *
 * Without a boundary React unmounts the whole tree on an uncaught render error, and the window
 * stays empty forever with nothing to click. This shows what happened and a Reload button, and
 * can clear the parts of local state that most often cause a crash loop.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[LocalMind] UI crashed:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex h-screen w-screen items-center justify-center bg-brand-bg-app p-6 text-center">
        <div className="max-w-md">
          <h1 className="mb-2 text-sm font-medium text-brand-green-soft">LocalMind hit a problem showing this screen</h1>
          <p className="mb-3 break-words text-[11px] text-brand-green-muted">{this.state.error.message}</p>
          <div className="flex justify-center gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded border border-brand-green/40 bg-brand-green/10 px-3 py-1 text-[11px] text-brand-green hover:bg-brand-green/20"
            >
              Reload
            </button>
            <button
              type="button"
              onClick={() => {
                try {
                  localStorage.clear();
                } catch {
                  /* storage unavailable */
                }
                window.location.reload();
              }}
              className="rounded border border-brand-border px-3 py-1 text-[11px] text-brand-green-muted hover:text-brand-green"
              title="Clears saved layout and theme, then reloads. Your chats are not affected."
            >
              Reset view and reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}

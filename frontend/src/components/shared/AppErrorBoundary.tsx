/**
 * AppErrorBoundary — a render crash must never leave a blank window.
 *
 * Without a boundary React unmounts the whole tree on an uncaught render error, and the window
 * stays empty forever with nothing to click. This shows what happened and a Reload button, and
 * can clear the parts of local state that most often cause a crash loop. Regions with their own
 * RecoveryBoundary recover smaller; this wall is what a crash outside those still hits, so it
 * also hands the user a paste-ready crash report.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { buildCrashReport } from '@/lib/localmind/crashReport';

interface State {
  error: Error | null;
  componentStack: string | null;
  copied: boolean;
  showDetails: boolean;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, componentStack: null, copied: false, showDetails: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[LocalMind] UI crashed:', error, info.componentStack);
    this.setState({ componentStack: info.componentStack ?? null, copied: false, showDetails: false });
  }

  private copyReport = async () => {
    const { error, componentStack } = this.state;
    if (!error) return;
    try {
      await navigator.clipboard.writeText(buildCrashReport(error, componentStack));
      this.setState({ copied: true });
    } catch {
      this.setState({ showDetails: true, copied: false });
    }
  };

  render() {
    const { error, componentStack, copied, showDetails } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" className="flex h-screen w-screen items-center justify-center bg-brand-bg-app p-6 text-center">
        <div className="max-w-md">
          <h1 className="mb-2 text-sm font-medium text-brand-green-soft">LocalMind hit a problem showing this screen</h1>
          <p className="mb-3 break-words text-[11px] text-brand-green-muted">{error.message}</p>
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
              onClick={this.copyReport}
              className="rounded border border-brand-border px-3 py-1 text-[11px] text-brand-green-muted hover:text-brand-green"
            >
              {copied ? 'Copied' : 'Copy details'}
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
          {showDetails && (
            <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded border border-brand-border p-2 text-left font-mono text-[10px] text-brand-green-muted">
              {buildCrashReport(error, componentStack)}
            </pre>
          )}
        </div>
      </div>
    );
  }
}

/**
 * RecoveryBoundary — a crash in one region must not take the app down.
 *
 * The top-level AppErrorBoundary answers a crash with a full-screen wall and
 * a page reload — right for chrome the app cannot live without, heavy for a
 * side panel: the conversation, the composer draft and every other region
 * were fine. This boundary scopes recovery to its own region. The crash card
 * replaces only the crashed subtree; "Try again" remounts it without a
 * reload, so the rest of the app and its state stay exactly as they were;
 * "Copy details" hands the user a paste-ready crash report; a full reload
 * stays one click away as the last resort. A region that crashes twice in a
 * row says so, instead of silently offering the same button again.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { buildCrashReport } from '@/lib/localmind/crashReport';

interface State {
  error: Error | null;
  componentStack: string | null;
  /** Consecutive crashes of this region without a clean re-mount between them. */
  crashes: number;
  copied: boolean;
  showDetails: boolean;
}

const INITIAL: State = { error: null, componentStack: null, crashes: 0, copied: false, showDetails: false };

export class RecoveryBoundary extends Component<{ label: string; children: ReactNode }, State> {
  state: State = INITIAL;

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[LocalMind] ${this.props.label} crashed:`, error, info.componentStack);
    this.setState((s) => ({
      componentStack: info.componentStack ?? null,
      crashes: s.crashes + 1,
      copied: false,
      showDetails: false,
    }));
  }

  componentDidUpdate(_prevProps: unknown, prev: State) {
    // A clean re-mount after "Try again" ends the crash streak; componentDidCatch
    // runs before this hook on a re-crash, so a streak in progress is not reset here.
    if (prev.error && !this.state.error && this.state.crashes !== 0) {
      this.setState({ crashes: 0 });
    }
  }

  private tryAgain = () => {
    this.setState({ error: null, componentStack: null, copied: false, showDetails: false });
  };

  private copyReport = async () => {
    const { error, componentStack } = this.state;
    if (!error) return;
    try {
      await navigator.clipboard.writeText(buildCrashReport(error, componentStack));
      this.setState({ copied: true });
    } catch {
      // Clipboard refused or does not exist — lay the report out so it can be copied by hand.
      this.setState({ showDetails: true, copied: false });
    }
  };

  render() {
    const { error, componentStack, crashes, copied, showDetails } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" className="flex h-full w-full items-center justify-center overflow-auto bg-brand-bg-app p-6">
        <div className="max-w-md text-center">
          <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-brand-amber" aria-hidden />
          <h1 className="mb-1 text-sm font-medium text-brand-green-soft">{this.props.label} hit a problem</h1>
          <p className="mb-3 break-words text-[11px] text-brand-green-muted">{error.message}</p>
          {crashes >= 2 && (
            <p className="mb-3 text-[11px] text-brand-amber">This keeps happening here — a full reload may help.</p>
          )}
          <div className="flex justify-center gap-2">
            <button
              type="button"
              onClick={this.tryAgain}
              className="rounded border border-brand-green/40 bg-brand-green/10 px-3 py-1 text-[11px] text-brand-green hover:bg-brand-green/20"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={this.copyReport}
              className="rounded border border-brand-border px-3 py-1 text-[11px] text-brand-green-muted hover:text-brand-green"
            >
              {copied ? 'Copied' : 'Copy details'}
            </button>
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-3 text-[10.5px] text-brand-green-muted underline-offset-2 hover:text-brand-green hover:underline"
          >
            Full reload
          </button>
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

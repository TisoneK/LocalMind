/**
 * WelcomeScreen — the first thing you see, and what an empty chat shows.
 *
 * It says the app is alive (a status line that tells the truth about the local engine), greets
 * you, and offers six real things to try, one click each. LocalMind is a general assistant
 * (files, the web, the machine, memory, research, code), so the starters span that range.
 */

import { Brain, Cpu } from 'lucide-react';
import { motion } from 'framer-motion';
import { useEnterMotion } from '@/lib/localmind/motion';
import { STARTERS, greetingFor } from '@/lib/localmind/welcomeContent';
import type { EngineStatus } from '@/lib/localmind/welcomeContent';

const STATUS_COPY: Record<EngineStatus, { text: string; dot: string }> = {
  online: { text: 'Ready · everything runs on your machine', dot: 'bg-brand-green' },
  checking: { text: 'Starting the local engine…', dot: 'bg-brand-amber animate-pulse' },
  offline: { text: "Can't reach the local engine — retrying", dot: 'bg-brand-red animate-pulse' },
};

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-brand-border bg-brand-bg-rail px-1 py-px font-mono text-[9.5px] text-brand-green-soft">
      {children}
    </kbd>
  );
}

interface WelcomeScreenProps {
  onPick: (prompt: string) => void;
  /** State of the local engine; starters wait until it is online. */
  status?: EngineStatus;
  memoryCount?: number;
  /** Injected for tests. */
  hour?: number;
}

export function WelcomeScreen({ onPick, status = 'online', memoryCount = 0, hour = new Date().getHours() }: WelcomeScreenProps) {
  const { reduce, enter } = useEnterMotion();
  const ready = status === 'online';
  const state = STATUS_COPY[status];

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-6 overflow-hidden px-6 text-center" data-testid="welcome" data-status={status}>
      {/* A soft glow behind the mark; decoration only. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[18%] h-64 w-64 -translate-x-1/2 rounded-full bg-brand-green/[0.07] blur-3xl"
      />

      <motion.div {...enter({ y: 6, duration: 0.35 })} className="relative flex flex-col items-center gap-4">
        <div className="relative">
          {!ready && !reduce && <span aria-hidden className="absolute inset-0 animate-ping rounded-2xl bg-brand-green/20" />}
          <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-brand-green/30 bg-gradient-to-br from-brand-green/20 to-brand-green/5 shadow-lg shadow-brand-green/10">
            <Cpu className="h-7 w-7 text-brand-green" />
          </div>
        </div>
        <div>
          <p className="mb-0.5 text-[11px] uppercase tracking-[0.18em] text-brand-green-muted">{greetingFor(hour)}</p>
          <h2 className="text-lg font-medium text-brand-green-soft">What can I do for you?</h2>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2 text-[10.5px] text-brand-green-muted" data-testid="welcome-status">
          <span className="flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-bg-rail px-2.5 py-1">
            <span className={`h-1.5 w-1.5 rounded-full ${state.dot}`} aria-hidden />
            {state.text}
          </span>
          {memoryCount > 0 && (
            <span className="flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-bg-rail px-2.5 py-1">
              <Brain className="h-3 w-3 text-brand-purple" aria-hidden />
              {memoryCount} {memoryCount === 1 ? 'memory' : 'memories'}
            </span>
          )}
        </div>
      </motion.div>

      <div className="relative grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
        {STARTERS.map(({ icon: Icon, label, prompt, tone }, i) => (
          <motion.button
            key={label}
            type="button"
            disabled={!ready}
            onClick={() => onPick(prompt)}
            {...enter({ y: 8, duration: 0.3 + i * 0.05 })}
            className="group flex items-start gap-2.5 rounded-xl border border-brand-border bg-brand-bg-rail px-3 py-2.5 text-left transition-all hover:-translate-y-px hover:border-brand-green/40 hover:bg-brand-green/[0.04] hover:shadow-md hover:shadow-black/20 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
          >
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${tone}`}>
              <Icon className="h-3.5 w-3.5" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-[11.5px] font-medium text-brand-green-soft">{label}</span>
              <span className="line-clamp-2 text-[10.5px] leading-snug text-brand-green-muted">{prompt}</span>
            </span>
          </motion.button>
        ))}
      </div>

      <p className="relative flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[10px] text-brand-green-faint">
        <span><Kbd>⌘K</Kbd> search chats</span>
        <span><Kbd>⌘N</Kbd> new chat</span>
        <span><Kbd>Esc</Kbd> stop the agent</span>
      </p>
    </div>
  );
}

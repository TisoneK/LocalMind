/**
 * WelcomeScreen — the empty chat. Instead of a blurb, it offers a handful of real things to try,
 * one click each. LocalMind is a general assistant (files, the web, the machine, memory,
 * research, code), so the starters span that range rather than leaning on coding.
 */

import { Cpu, FileText, Globe, HardDrive, Brain, Code2, Newspaper } from 'lucide-react';
import type { ComponentType } from 'react';

interface Starter {
  icon: ComponentType<{ className?: string }>;
  label: string;
  prompt: string;
}

export const STARTERS: Starter[] = [
  { icon: HardDrive, label: 'Check my machine', prompt: 'How much free disk space and memory do I have right now?' },
  { icon: Globe, label: 'Look something up', prompt: "What's the weather in Nairobi right now?" },
  { icon: Newspaper, label: 'Catch me up', prompt: 'Search the web for the top tech news today and summarise it in five bullets.' },
  { icon: FileText, label: 'Make a file', prompt: 'Create a folder called notes and put a todo.md in it with a short plan for my week.' },
  { icon: Brain, label: 'Remember something', prompt: "Remember that I prefer short answers with the key point first." },
  { icon: Code2, label: 'Explore a project', prompt: 'List the files in my current folder and tell me what this project does.' },
];

export function WelcomeScreen({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-6 text-center" data-testid="welcome">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-green/10">
        <Cpu className="h-6 w-6 text-brand-green" />
      </div>
      <div>
        <h2 className="mb-1 text-sm font-medium text-brand-green-soft">What can I do for you?</h2>
        <p className="mx-auto max-w-sm text-[11px] text-brand-green-muted">
          I work on your machine: files, commands, the web, and things you ask me to remember. Pick one, or just type.
        </p>
      </div>
      <div className="grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
        {STARTERS.map(({ icon: Icon, label, prompt }) => (
          <button
            key={label}
            type="button"
            onClick={() => onPick(prompt)}
            className="group flex items-start gap-2 rounded-lg border border-brand-border bg-brand-bg-rail px-3 py-2 text-left transition-colors hover:border-brand-green/40 hover:bg-brand-green/5"
          >
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-green-muted group-hover:text-brand-green" />
            <span className="min-w-0">
              <span className="block text-[11.5px] font-medium text-brand-green-soft">{label}</span>
              <span className="line-clamp-2 text-[10.5px] text-brand-green-muted">{prompt}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

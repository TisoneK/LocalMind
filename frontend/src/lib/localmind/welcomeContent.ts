import type { LucideIcon } from 'lucide-react';
import { Brain, Code2, FileText, Globe, HardDrive, Newspaper } from 'lucide-react';

export type EngineStatus = 'online' | 'offline' | 'checking';

export interface Starter {
  icon: LucideIcon;
  label: string;
  prompt: string;
  /** Tile colour, from the same palette as the tool icons. */
  tone: string;
}

export const STARTERS: Starter[] = [
  { icon: HardDrive, label: 'Check my machine', prompt: 'How much free disk space and memory do I have right now?', tone: 'text-brand-amber bg-brand-amber/10' },
  { icon: Globe, label: 'Look something up', prompt: "What's the weather in Nairobi right now?", tone: 'text-brand-blue bg-brand-blue/10' },
  { icon: Newspaper, label: 'Catch me up', prompt: 'Search the web for the top tech news today and summarise it in five bullets.', tone: 'text-brand-purple bg-brand-purple/10' },
  { icon: FileText, label: 'Make a file', prompt: 'Create a folder called notes and put a todo.md in it with a short plan for my week.', tone: 'text-brand-green bg-brand-green/10' },
  { icon: Brain, label: 'Remember something', prompt: 'Remember that I prefer short answers with the key point first.', tone: 'text-brand-purple bg-brand-purple/10' },
  { icon: Code2, label: 'Explore a project', prompt: 'List the files in my current folder and tell me what this project does.', tone: 'text-brand-blue bg-brand-blue/10' },
];

/** "Good morning" / "Good afternoon" / "Good evening" for a given hour (0-23). */
export function greetingFor(hour: number): string {
  if (hour < 5) return 'Still up?';
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

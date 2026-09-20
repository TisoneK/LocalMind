/**
 * One glyph and one colour per kind of work, so a list of steps can be read at a glance:
 * web is blue, reading/searching the machine is cyan, writing is amber, commands are green,
 * memory is purple. Shared by every place a step is drawn (turn view, rail).
 */

import { Bot, Brain, FileEdit, FileSearch, Globe, Search, Terminal, Wrench, type LucideIcon } from 'lucide-react';

export interface ToolIconMeta {
  Icon: LucideIcon;
  /** Tailwind text colour for the glyph. */
  tone: string;
  /** A short word for the kind of work — used as the icon's accessible name. */
  kind: string;
}

const WEB: ToolIconMeta = { Icon: Globe, tone: 'text-brand-blue', kind: 'web' };
const READ: ToolIconMeta = { Icon: FileSearch, tone: 'text-cyan-300', kind: 'read' };
const FIND: ToolIconMeta = { Icon: Search, tone: 'text-cyan-300', kind: 'search' };
const WRITE: ToolIconMeta = { Icon: FileEdit, tone: 'text-brand-amber', kind: 'write' };
const RUN: ToolIconMeta = { Icon: Terminal, tone: 'text-brand-green', kind: 'command' };
const MEMORY: ToolIconMeta = { Icon: Brain, tone: 'text-brand-purple', kind: 'memory' };
const AGENT: ToolIconMeta = { Icon: Bot, tone: 'text-brand-purple', kind: 'agent' };
const OTHER: ToolIconMeta = { Icon: Wrench, tone: 'text-brand-green-muted', kind: 'tool' };

const BY_TOOL: Record<string, ToolIconMeta> = {
  web_search: WEB,
  web_fetch: WEB,
  browse: WEB,
  file_read: READ,
  file_task: READ,
  dir_explorer: READ,
  system_search: FIND,
  find_path: FIND,
  grep: FIND,
  grep_search: FIND,
  file_write: WRITE,
  edit_file: WRITE,
  propose_write_file: WRITE,
  propose_str_replace: WRITE,
  apply_proposed_edit: WRITE,
  shell: RUN,
  code_exec: RUN,
  process: RUN,
  git: RUN,
  memory_op: MEMORY,
  delegate: AGENT,
  delegate_parallel: AGENT,
};

export function toolIconMeta(name: string | undefined): ToolIconMeta {
  return (name && BY_TOOL[name]) || OTHER;
}

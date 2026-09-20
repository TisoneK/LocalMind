/**
 * ActivityRail — the live "state of the world" beside the chat.
 *
 * Four glanceable sections instead of a tree to dig through: what is running
 * this second, the plan, the agents involved, and the files the turn touched.
 * The detailed per-run tree stays one click away under "Run details".
 */

import { useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Bot, ChevronRight, FileText } from 'lucide-react';
import type { ActionItem, AgentRun, DiffData, TodoItem } from '@/types';
import { buildRail } from '@/lib/localmind/activityRail';
import { useEnterMotion } from '@/lib/localmind/motion';
import { StateIcon } from '@/components/chat/StateIcon';
import { ToolIcon } from '@/components/chat/ToolIcon';
import { useElapsedSeconds } from '@/lib/localmind/useElapsedSeconds';
import { AgentWorkspace } from '@/components/panels/AgentWorkspace';
import { TodoList } from '@/components/panels/TodoList';

interface ActivityRailProps {
  runs: AgentRun[];
  /** The session's tasks — the one place the plan is shown and edited. */
  todos?: TodoItem[];
  /** Actions per task, for the count badge and the highlighted active step. */
  actions?: ActionItem[];
  onToggleTodo?: (id: string, completed: boolean) => void;
  onAddTodo?: (text: string) => void;
  /** Cancel the running turn; the button shows while something is running. */
  onAbort?: () => void;
  fileDiffs?: Record<string, DiffData>;
  isStreaming?: boolean;
  /** The reply text is streaming in (no tool running): the agent is writing, not deciding. */
  answering?: boolean;
}

function Section({
  title,
  count,
  action,
  live,
  children,
}: {
  title: string;
  count?: string;
  action?: ReactNode;
  /** The section is showing something happening right now — give it visual priority. */
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={`border-b border-white/[0.06] px-3 py-2.5 ${live ? 'bg-brand-amber/[0.04]' : ''}`}>
      <div
        className={`mb-1.5 flex items-center justify-between text-[10px] font-medium uppercase tracking-wider ${
          live ? 'text-brand-amber' : 'text-brand-green-muted'
        }`}
      >
        <span>{title}</span>
        <span className="flex items-center gap-2 normal-case tracking-normal">
          {count}
          {action}
        </span>
      </div>
      {children}
    </section>
  );
}

function NowRow({ tool, label, agent, detail }: { tool: string; label: string; agent: string; detail?: string }) {
  const { enter } = useEnterMotion();
  const secs = useElapsedSeconds(true);
  return (
    <motion.div {...enter({ x: 6 })} className="flex items-center gap-2 rounded bg-brand-amber/[0.05] px-1.5 py-1 text-[11.5px]">
      <StateIcon state="running" />
      <ToolIcon name={tool} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-brand-green">{label}</div>
        <div className="truncate text-[10px] text-brand-green-muted">
          {agent}
          {detail ? ` · ${detail}` : ''}
        </div>
      </div>
      <span className="shrink-0 text-[10px] text-brand-green-muted">{secs}s</span>
    </motion.div>
  );
}

export function ActivityRail({ runs, todos = [], actions, onToggleTodo, onAddTodo, onAbort, fileDiffs, isStreaming, answering }: ActivityRailProps) {
  const rail = buildRail({ runs, fileDiffs, isStreaming });
  const [details, setDetails] = useState(false);
  const live = rail.now.length > 0 || !!isStreaming;
  // Tasks sit right under "Now" (or under the idle note) so the plan reads next to what is running.
  const tasksSection = (
    <section className="border-b border-white/[0.06] px-3 py-2.5" data-testid="rail-tasks">
      <TodoList todos={todos} actions={actions} onToggle={onToggleTodo} onAdd={onAddTodo} settled={isStreaming === false} />
    </section>
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto" data-testid="activity-rail">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2">
        <span className="text-[12px] font-medium text-brand-green">Activity</span>
        <span className={`flex items-center gap-1.5 text-[10px] ${live ? 'text-brand-amber' : 'text-brand-green-muted'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${live ? 'animate-pulse bg-brand-amber' : 'bg-brand-green-muted/50'}`} />
          {live ? 'live' : 'idle'}
        </span>
      </div>

      {rail.empty && !live ? (
        <>
        <p className="px-3 py-4 text-[11.5px] text-brand-green-muted">
          Nothing running. Agent work — what is running, the plan and the files it touches — shows up here as it happens.
        </p>
        {tasksSection}
        </>
      ) : (
        <>
          {live && (
          <Section
            live
            title="Now"
            count={rail.now.length > 0 ? `${rail.now.length} running` : undefined}
            action={
              onAbort && live ? (
                <button
                  type="button"
                  onClick={onAbort}
                  title="Cancel the running turn"
                  className="rounded border border-red-400/30 bg-red-400/10 px-1.5 py-0.5 text-[9px] font-medium text-red-300 hover:bg-red-400/20"
                >
                  Cancel
                </button>
              ) : undefined
            }
          >
            {rail.now.length > 0 ? (
              <div className="space-y-1">
                {rail.now.map((n) => (
                  <NowRow key={n.id} tool={n.tool} label={n.label} agent={n.agent} detail={n.detail} />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-brand-green-muted">{answering ? 'Writing the answer…' : 'Deciding the next step…'}</p>
            )}
          </Section>
          )}

          {tasksSection}

          {/* One agent adds nothing the turn view doesn't already say; show the roster only when there are several. */}
          {rail.agents.length > 1 && (
            <Section title="Agents" count={String(rail.agents.length)}>
              <ul className="space-y-1">
                {rail.agents.map((a) => (
                  <li key={a.id} className="flex items-center gap-2 text-[11.5px]">
                    <StateIcon state={a.state} />
                    <Bot className="h-3 w-3 shrink-0 text-brand-green-muted" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-brand-green">{a.name}</span>
                    <span className="shrink-0 text-[10px] text-brand-green-muted">
                      {a.toolsDone}/{a.toolsTotal} tools
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {rail.files.length > 0 && (
            <Section title="Files changed" count={String(rail.files.length)}>
              <ul className="space-y-1">
                {rail.files.map((f) => (
                  <li key={f.path} className="flex items-center gap-2 text-[11.5px]">
                    <FileText className="h-3 w-3 shrink-0 text-brand-green-muted" aria-hidden />
                    <button
                      type="button"
                      onClick={() => window.dispatchEvent(new CustomEvent('localmind:open-file-preview', { detail: f.path }))}
                      title={`Preview ${f.path}`}
                      className="min-w-0 flex-1 truncate text-left text-brand-green hover:text-brand-blue-bright"
                    >
                      {f.name}
                    </button>
                    {(f.additions > 0 || f.deletions > 0) && (
                      <span className="shrink-0 font-mono text-[10px]">
                        <span className="text-brand-green">+{f.additions}</span> <span className="text-red-400">−{f.deletions}</span>
                      </span>
                    )}
                    <StateIcon state={f.state} className="h-3 w-3" />
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}

      <div className="mt-auto">
        <button
          type="button"
          onClick={() => setDetails((d) => !d)}
          aria-expanded={details}
          className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[10.5px] text-brand-green-muted hover:text-brand-green"
        >
          <ChevronRight className={`h-3 w-3 transition-transform ${details ? 'rotate-90' : ''}`} aria-hidden />
          Run details
        </button>
        {details && <AgentWorkspace runs={runs} isStreaming={isStreaming} />}
      </div>
    </div>
  );
}

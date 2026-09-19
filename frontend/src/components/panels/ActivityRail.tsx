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
import type { AgentRun, DiffData, TodoItem } from '@/types';
import { buildRail } from '@/lib/localmind/activityRail';
import { useEnterMotion } from '@/lib/localmind/motion';
import { StateIcon } from '@/components/chat/StateIcon';
import { useElapsedSeconds } from '@/lib/localmind/useElapsedSeconds';
import { AgentWorkspace } from '@/components/panels/AgentWorkspace';

interface ActivityRailProps {
  runs: AgentRun[];
  todos?: TodoItem[];
  fileDiffs?: Record<string, DiffData>;
  isStreaming?: boolean;
}

function Section({ title, count, children }: { title: string; count?: string; children: ReactNode }) {
  return (
    <section className="border-b border-white/[0.06] px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-brand-green-muted">
        <span>{title}</span>
        {count && <span className="normal-case tracking-normal">{count}</span>}
      </div>
      {children}
    </section>
  );
}

function NowRow({ label, agent, detail }: { label: string; agent: string; detail?: string }) {
  const { enter } = useEnterMotion();
  const secs = useElapsedSeconds(true);
  return (
    <motion.div {...enter({ x: 6 })} className="flex items-center gap-2 rounded bg-brand-amber/[0.05] px-1.5 py-1 text-[11.5px]">
      <StateIcon state="running" />
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

export function ActivityRail({ runs, todos, fileDiffs, isStreaming }: ActivityRailProps) {
  const rail = buildRail({ runs, todos, fileDiffs, isStreaming });
  const [details, setDetails] = useState(false);
  const live = rail.now.length > 0 || !!isStreaming;

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
        <p className="px-3 py-4 text-[11.5px] text-brand-green-muted">
          Nothing running. Agent work — what is running, the plan and the files it touches — shows up here as it happens.
        </p>
      ) : (
        <>
          <Section title="Now" count={rail.now.length > 0 ? `${rail.now.length} running` : undefined}>
            {rail.now.length > 0 ? (
              <div className="space-y-1">
                {rail.now.map((n) => (
                  <NowRow key={n.id} label={n.label} agent={n.agent} detail={n.detail} />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-brand-green-muted">{live ? 'Deciding the next step…' : 'Nothing running.'}</p>
            )}
          </Section>

          {rail.plan && (
            <Section title="Plan" count={`${rail.plan.done}/${rail.plan.total}`}>
              <div className="mb-2 h-1 overflow-hidden rounded-full bg-white/10" aria-hidden>
                <div
                  className="h-full rounded-full bg-brand-green transition-[width] duration-500"
                  style={{ width: `${(rail.plan.done / rail.plan.total) * 100}%` }}
                />
              </div>
              <ul className="space-y-1">
                {rail.plan.items.map((i) => (
                  <li key={i.id} className={`flex items-start gap-2 text-[11.5px] ${i.state === 'pending' ? 'text-brand-green-muted' : 'text-brand-green'}`}>
                    <span className="mt-0.5">
                      <StateIcon state={i.state} />
                    </span>
                    <div className="min-w-0">
                      <span className={i.state === 'done' ? 'line-through decoration-white/20' : ''}>{i.label}</span>
                      {i.children && (
                        <ul className="mt-0.5 space-y-0.5 border-l border-white/10 pl-2.5">
                          {i.children.map((c) => (
                            <li key={c.id} className="flex items-center gap-1.5 text-[10.5px] text-brand-green-muted">
                              <StateIcon state={c.state} className="h-3 w-3" />
                              {c.label}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {rail.agents.length > 0 && (
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
                  <li key={f.path} className="flex items-center gap-2 text-[11.5px]" title={f.path}>
                    <FileText className="h-3 w-3 shrink-0 text-brand-green-muted" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-brand-green">{f.name}</span>
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

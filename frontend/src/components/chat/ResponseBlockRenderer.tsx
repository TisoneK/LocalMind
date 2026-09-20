/**
 * Response Block Renderer
 *
 * Renders structured ResponseBlocks natively in the UI.
 * The agent decides WHAT to show; the UI decides HOW it looks.
 *
 * Block types:
 * - text → existing MarkdownContent renderer
 * - table → native HTML table with semantic tones
 * - code → existing code block renderer
 * - metric → compact metric card with tone color
 * - list → ordered/unordered list
 * - diagram → placeholder (Phase 5: SVG/graph renderer)
 * - chart → placeholder (Phase 5: chart renderer)
 * - mixed → render nested blocks in sequence
 */
'use client';

import { motion } from 'framer-motion';
import {
  useEnterMotion,
  type EnterOptions,
  type EnterMotionProps,
} from '@/lib/localmind/motion';
import { Check, HelpCircle, Minus } from 'lucide-react';
import type { ResponseBlock, Tone, InfoState } from '@/types/response-blocks';

/** Spreadable enter-motion props handed down to sub-renderers. */
type EnterMotionFn = (opts?: EnterOptions) => EnterMotionProps;

// ── Tone → color mapping ────────────────────────────────────────────────────

const TONE_COLORS: Record<Tone, { text: string; bg: string; border: string }> = {
  success: { text: 'text-brand-green', bg: 'bg-brand-green/10', border: 'border-brand-green/30' },
  warning: { text: 'text-brand-amber', bg: 'bg-brand-amber/10', border: 'border-brand-amber/30' },
  error: { text: 'text-red-400', bg: 'bg-red-400/10', border: 'border-red-400/30' },
  info: { text: 'text-brand-blue', bg: 'bg-brand-blue/10', border: 'border-brand-blue/30' },
  neutral: { text: 'text-brand-green-muted', bg: 'bg-brand-bg-code', border: 'border-brand-border' },
  primary: { text: 'text-brand-green', bg: 'bg-brand-green/5', border: 'border-brand-green/20' },
  accent: { text: 'text-brand-purple', bg: 'bg-brand-purple/10', border: 'border-brand-purple/30' },
};

function getToneColors(tone?: Tone) {
  return TONE_COLORS[tone || 'neutral'] || TONE_COLORS.neutral;
}

// ── Info state icons ────────────────────────────────────────────────────────

function InfoStateIcon({ state }: { state?: InfoState }) {
  if (!state) return null;
  const icons = {
    confirmed: <Check className="h-3 w-3 text-brand-green" />,
    inferred: <Minus className="h-3 w-3 text-brand-amber" />,
    needs_verification: <HelpCircle className="h-3 w-3 text-brand-amber" />,
  };
  return <span className="inline-flex items-center">{icons[state]}</span>;
}

// ── Sub-renderers ────────────────────────────────────────────────────────────

function TextBlockRenderer({ block }: { block: ResponseBlock }) {
  // Text blocks use the existing MarkdownContent renderer via a simple div.
  // The parent ChatMessage already renders content via MarkdownContent,
  // so for text blocks we just render the content in a div.
  return (
    <div className="text-[13px] text-brand-green-soft leading-relaxed break-words">
      {block.info_state && (
        <span className="mr-1.5 inline-flex items-center align-middle">
          <InfoStateIcon state={block.info_state} />
        </span>
      )}
      {block.content}
    </div>
  );
}

function TableBlockRenderer({ block, enter }: { block: ResponseBlock; enter: EnterMotionFn }) {
  if (!block.columns || !block.rows) return null;
  const colors = getToneColors(block.tone);
  return (
    <motion.div {...enter({ y: 3, duration: 0.2 })} className="my-3">
      {block.title && (
        <div className={`text-[11px] font-medium uppercase tracking-wider mb-1.5 ${colors.text}`}>
          {block.title}
        </div>
      )}
      <div className="overflow-x-auto rounded-md border border-brand-border">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-brand-bg-code">
              {block.columns.map((col, i) => (
                <th
                  key={i}
                  className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium text-brand-green-muted border-b border-brand-border"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-brand-border/50 last:border-0 hover:bg-brand-bg-rail/50 transition-colors"
              >
                {row.map((cell, j) => (
                  <td
                    key={j}
                    // Short values (ranks, points, scores) stay on one line so a narrow column
                    // never wraps a number; long text (a team name) may wrap instead.
                    className={`px-2.5 py-1.5 text-brand-green-soft ${String(cell).length <= 14 ? 'whitespace-nowrap' : 'min-w-[6.5rem]'}`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}

function MetricBlockRenderer({ block, enter }: { block: ResponseBlock; enter: EnterMotionFn }) {
  const colors = getToneColors(block.tone);
  return (
    <motion.div
      {...enter({ y: 3, duration: 0.2 })}
      className={`inline-flex flex-col items-center rounded-md border ${colors.border} ${colors.bg} px-4 py-2 my-2`}
    >
      <span className={`text-2xl font-bold ${colors.text}`}>{block.value}</span>
      <span className="text-[10px] uppercase tracking-wider text-brand-green-muted mt-0.5">
        {block.label}
      </span>
    </motion.div>
  );
}

function CodeBlockRenderer({ block }: { block: ResponseBlock }) {
  // Code blocks use a simple pre + code — the parent ChatMessage already
  // has MarkdownContent which handles code blocks, so this is a lightweight
  // fallback for when code arrives as a structured block.
  const lang = block.metadata?.language as string | undefined;
  return (
    <div className="my-2 overflow-x-auto rounded-md border border-brand-border bg-brand-bg-code">
      {lang && (
        <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-brand-green-muted border-b border-brand-border">
          {lang}
        </div>
      )}
      <pre className="px-3 py-2 text-[12px] text-brand-green-soft overflow-x-auto">
        <code>{block.content}</code>
      </pre>
    </div>
  );
}

function ListBlockRenderer({ block }: { block: ResponseBlock }) {
  if (!block.items) return null;
  const ordered = block.metadata?.ordered as boolean | undefined;
  return (
    <div className="my-2">
      {ordered ? (
        <ol className="list-decimal list-inside space-y-1 text-[13px] text-brand-green-soft">
          {block.items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ol>
      ) : (
        <ul className="list-disc list-inside space-y-1 text-[13px] text-brand-green-soft">
          {block.items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DiagramBlockRenderer({ block }: { block: ResponseBlock }) {
  // Phase 5 placeholder — semantic diagram rendering (nodes + edges → SVG)
  // For now, render a compact summary of the diagram structure.
  return (
    <div className="my-3 rounded-md border border-brand-border bg-brand-bg-code p-3">
      {block.title && (
        <div className="text-[11px] font-medium uppercase tracking-wider text-brand-green-muted mb-2">
          {block.title}
        </div>
      )}
      <div className="text-[11px] text-brand-green-muted">
        {block.diagram_type} diagram — {block.nodes?.length || 0} nodes, {block.edges?.length || 0} edges
      </div>
      {block.nodes && block.nodes.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {block.nodes.map((node, i) => (
            <div key={i} className="text-[12px] text-brand-green-soft">
              • {node.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChartBlockRenderer({ block }: { block: ResponseBlock }) {
  // Phase 5 placeholder — chart rendering (bar/line/pie)
  // For now, render a compact data summary.
  return (
    <div className="my-3 rounded-md border border-brand-border bg-brand-bg-code p-3">
      {block.title && (
        <div className="text-[11px] font-medium uppercase tracking-wider text-brand-green-muted mb-2">
          {block.title}
        </div>
      )}
      <div className="text-[11px] text-brand-green-muted mb-2">
        {block.chart_type} chart — {block.data?.length || 0} data points
      </div>
      {block.data && block.data.length > 0 && (
        <div className="space-y-0.5">
          {block.data.map((point, i) => (
            <div key={i} className="flex items-center gap-2 text-[12px]">
              <span className="text-brand-green-soft">{point.label}:</span>
              <span className="text-brand-green-muted">{point.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main renderer ────────────────────────────────────────────────────────────

export function ResponseBlockRenderer({ blocks }: { blocks: ResponseBlock[] }) {
  // Hooks must run before any early return (same order every render).
  const { enter } = useEnterMotion();

  // Filter out presentation_hint blocks (they're metadata, not visual)
  const visualBlocks = (blocks || []).filter((b) => b.type !== 'presentation_hint');

  if (visualBlocks.length === 0) return null;

  return (
    <div className="space-y-1">
      {visualBlocks.map((block, i) => {
        switch (block.type) {
          case 'text':
            return <TextBlockRenderer key={i} block={block} />;
          case 'table':
            return <TableBlockRenderer key={i} block={block} enter={enter} />;
          case 'metric':
            return <MetricBlockRenderer key={i} block={block} enter={enter} />;
          case 'code':
            return <CodeBlockRenderer key={i} block={block} />;
          case 'list':
            return <ListBlockRenderer key={i} block={block} />;
          case 'diagram':
            return <DiagramBlockRenderer key={i} block={block} />;
          case 'chart':
            return <ChartBlockRenderer key={i} block={block} />;
          case 'mixed':
            return block.blocks ? <ResponseBlockRenderer key={i} blocks={block.blocks} /> : null;
          default:
            // Unknown block type — render as text if content exists
            return block.content ? (
              <TextBlockRenderer key={i} block={block} />
            ) : null;
        }
      })}
    </div>
  );
}

/**
 * Response Block System (frontend types)
 *
 * The agent produces semantic blocks; the frontend renders them.
 * The agent decides WHAT to show; the UI decides HOW it looks.
 *
 * Core principle: The model decides the semantic form of the answer.
 * The UI owns its visual implementation.
 */

// ── Semantic tone — colors communicate meaning, not decoration ───────────────

export type Tone =
  | "success" // confirmed / passed / completed → green
  | "warning" // partial / needs attention → amber
  | "error" // failed / broken → red
  | "info" // neutral information → blue
  | "neutral" // default → gray
  | "primary" // key highlight → brand color
  | "accent"; // secondary highlight → accent color

// ── Information state — visual confidence indicators ─────────────────────────

export type InfoState =
  | "confirmed" // ✓ — data verified from source
  | "inferred" // ~ — agent inference
  | "needs_verification"; // ? — unverified claim

// ── Presentation type — the semantic form of the answer ─────────────────────

export type PresentationType =
  | "text" // plain text or markdown
  | "table" // structured table with columns + rows
  | "code" // syntax-highlighted code
  | "diagram" // semantic graph (nodes + edges) → renderer
  | "chart" // data series → bar/line/pie
  | "metric" // single value + label + tone
  | "card" // compact info card
  | "file" // file reference (name + path + excerpt)
  | "timeline" // ordered events with timestamps
  | "comparison" // side-by-side comparison
  | "list" // numbered/bulleted list
  | "mixed" // composite (multiple blocks in sequence)
  | "presentation_hint"; // metadata-only block (visual tone/cue hints), never rendered directly

// ── Diagram types ───────────────────────────────────────────────────────────

export type DiagramType =
  | "flow" // process flow
  | "architecture" // system architecture
  | "sequence" // interaction sequence
  | "hierarchy" // tree/org structure
  | "state" // state machine
  | "relationship"; // entity-relationship

// ── Chart types ─────────────────────────────────────────────────────────────

export type ChartType = "bar" | "line" | "pie" | "scatter";

// ── Response block schema ───────────────────────────────────────────────────

export interface DiagramNode {
  id: string;
  label: string;
  type?: string; // "user" | "agent" | "tool" | "memory" | "web" | etc.
}

export interface DiagramEdge {
  from: string;
  to: string;
  label?: string;
  type?: string; // "data" | "control" | "feedback"
}

export interface ChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

export interface TimelineEvent {
  timestamp: string;
  label: string;
  description?: string;
  tone?: Tone;
}

export interface ComparisonSide {
  title: string;
  items: string[];
  tone?: Tone;
}

export interface ResponseBlock {
  type: PresentationType;

  // Common
  content?: string; // for TEXT, CODE
  title?: string; // for TABLE, CHART, CARD
  tone?: Tone;
  info_state?: InfoState;

  // Table
  columns?: string[];
  rows?: string[][];

  // Diagram
  diagram_type?: DiagramType;
  nodes?: DiagramNode[];
  edges?: DiagramEdge[];

  // Chart
  chart_type?: ChartType;
  data?: ChartDataPoint[];

  // Metric
  value?: string;
  label?: string;

  // File
  file_name?: string;
  file_path?: string;
  file_excerpt?: string;

  // List
  items?: string[];
  ordered?: boolean;

  // Timeline
  events?: TimelineEvent[];

  // Comparison
  left?: ComparisonSide;
  right?: ComparisonSide;

  // Card
  metadata?: Record<string, unknown>;

  // Mixed
  blocks?: ResponseBlock[];
}

// ── Block factory helpers (mirrors the Python backend) ──────────────────────

export function textBlock(
  content: string,
  infoState?: InfoState
): ResponseBlock {
  return { type: "text", content, info_state: infoState };
}

export function tableBlock(
  title: string,
  columns: string[],
  rows: string[][],
  tone?: Tone
): ResponseBlock {
  return { type: "table", title, columns, rows, tone };
}

export function metricBlock(
  value: string,
  label: string,
  tone: Tone = "neutral"
): ResponseBlock {
  return { type: "metric", value, label, tone };
}

export function diagramBlock(
  diagramType: DiagramType,
  nodes: DiagramNode[],
  edges: DiagramEdge[],
  title?: string
): ResponseBlock {
  return {
    type: "diagram",
    diagram_type: diagramType,
    nodes,
    edges,
    title,
  };
}

export function codeBlock(
  content: string,
  language?: string
): ResponseBlock {
  return {
    type: "code",
    content,
    metadata: language ? { language } : undefined,
  };
}

export function listBlock(items: string[], ordered = false): ResponseBlock {
  return { type: "list", items, ordered };
}

export function mixedBlock(blocks: ResponseBlock[]): ResponseBlock {
  return { type: "mixed", blocks };
}

// ── SSE event: structured response blocks ───────────────────────────────────
//
// The backend emits this SSE event when the agent produces structured output.
// The frontend's ResponseBlockRenderer component consumes it.
//
// {"type": "response_blocks", "blocks": [...]}
//

export interface ResponseBlocksEvent {
  type: "response_blocks";
  blocks: ResponseBlock[];
}

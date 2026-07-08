'use client';

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  Copy,
  Check,
  FileCode2,
  ChevronDown,
  ChevronRight,
  FileSymlink,
  Expand,
  Shrink,
  MoreHorizontal,
} from 'lucide-react';

// ── Language display names (human-friendly) ──────────────────────────────
const LANGUAGE_LABELS: Record<string, string> = {
  js: 'JavaScript', javascript: 'JavaScript', jsx: 'JSX',
  ts: 'TypeScript', typescript: 'TypeScript', tsx: 'TSX',
  html: 'HTML', css: 'CSS', scss: 'SCSS', less: 'LESS',
  json: 'JSON', python: 'Python', py: 'Python',
  bash: 'Bash', sh: 'Shell', shell: 'Shell', sql: 'SQL',
  markdown: 'Markdown', md: 'Markdown', yaml: 'YAML', yml: 'YAML',
  xml: 'XML', java: 'Java', c: 'C', cpp: 'C++',
  csharp: 'C#', cs: 'C#', go: 'Go', rust: 'Rust',
  ruby: 'Ruby', rb: 'Ruby', php: 'PHP', swift: 'Swift',
  kotlin: 'Kotlin', dart: 'Dart', r: 'R', lua: 'Lua',
  perl: 'Perl', dockerfile: 'Dockerfile', makefile: 'Makefile',
  toml: 'TOML', ini: 'INI', diff: 'Diff',
  plaintext: 'Plain Text', text: 'Plain Text',
};

// ── File icon colors by language — themed to green-black palette ──────────
const LANG_ICON_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  html:   { bg: 'bg-[#e44d26]/15', text: 'text-[#e44d26]', border: 'border-[#e44d26]/30' },
  css:    { bg: 'bg-[#264de4]/15', text: 'text-[#264de4]', border: 'border-[#264de4]/30' },
  scss:   { bg: 'bg-[#cd6799]/15', text: 'text-[#cd6799]', border: 'border-[#cd6799]/30' },
  js:     { bg: 'bg-[#f7df1e]/15', text: 'text-[#f7df1e]', border: 'border-[#f7df1e]/30' },
  javascript: { bg: 'bg-[#f7df1e]/15', text: 'text-[#f7df1e]', border: 'border-[#f7df1e]/30' },
  ts:     { bg: 'bg-[#3178c6]/15', text: 'text-[#3178c6]', border: 'border-[#3178c6]/30' },
  typescript: { bg: 'bg-[#3178c6]/15', text: 'text-[#3178c6]', border: 'border-[#3178c6]/30' },
  tsx:    { bg: 'bg-[#3178c6]/15', text: 'text-[#3178c6]', border: 'border-[#3178c6]/30' },
  jsx:    { bg: 'bg-[#61dafb]/15', text: 'text-[#61dafb]', border: 'border-[#61dafb]/30' },
  python: { bg: 'bg-[#3572a5]/15', text: 'text-[#3572a5]', border: 'border-[#3572a5]/30' },
  py:     { bg: 'bg-[#3572a5]/15', text: 'text-[#3572a5]', border: 'border-[#3572a5]/30' },
  json:   { bg: 'bg-[#f7df1e]/15', text: 'text-[#f7df1e]', border: 'border-[#f7df1e]/30' },
  bash:   { bg: 'bg-[#39d353]/15', text: 'text-[#39d353]', border: 'border-[#39d353]/30' },
  sh:     { bg: 'bg-[#39d353]/15', text: 'text-[#39d353]', border: 'border-[#39d353]/30' },
  shell:  { bg: 'bg-[#39d353]/15', text: 'text-[#39d353]', border: 'border-[#39d353]/30' },
  sql:    { bg: 'bg-[#e8a420]/15', text: 'text-[#e8a420]', border: 'border-[#e8a420]/30' },
  go:     { bg: 'bg-[#00add8]/15', text: 'text-[#00add8]', border: 'border-[#00add8]/30' },
  rust:   { bg: 'bg-[#dea584]/15', text: 'text-[#dea584]', border: 'border-[#dea584]/30' },
  java:   { bg: 'bg-[#b07219]/15', text: 'text-[#b07219]', border: 'border-[#b07219]/30' },
  ruby:   { bg: 'bg-[#701516]/15', text: 'text-[#cc342d]', border: 'border-[#cc342d]/30' },
  rb:     { bg: 'bg-[#701516]/15', text: 'text-[#cc342d]', border: 'border-[#cc342d]/30' },
  php:    { bg: 'bg-[#4f5d95]/15', text: 'text-[#4f5d95]', border: 'border-[#4f5d95]/30' },
  yaml:   { bg: 'bg-[#cb171e]/15', text: 'text-[#cb171e]', border: 'border-[#cb171e]/30' },
  yml:    { bg: 'bg-[#cb171e]/15', text: 'text-[#cb171e]', border: 'border-[#cb171e]/30' },
  xml:    { bg: 'bg-[#e44d26]/15', text: 'text-[#e44d26]', border: 'border-[#e44d26]/30' },
  markdown: { bg: 'bg-[#39d353]/15', text: 'text-[#5af75a]', border: 'border-[#39d353]/30' },
  md:     { bg: 'bg-[#39d353]/15', text: 'text-[#5af75a]', border: 'border-[#39d353]/30' },
  dockerfile: { bg: 'bg-[#384d54]/15', text: 'text-[#384d54]', border: 'border-[#384d54]/30' },
};

const DEFAULT_LANG_STYLE = { bg: 'bg-[#8ab08a]/15', text: 'text-[#8ab08a]', border: 'border-[#8ab08a]/30' };

// ── Utility: format bytes ─────────────────────────────────────────────────
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ── Utility: count lines ──────────────────────────────────────────────────
function countLines(code: string): number {
  if (!code) return 0;
  return code.split('\n').length;
}

// ── Custom style matching the green-black theme ───────────────────────────
function getCustomStyle() {
  const custom = { ...vscDarkPlus };
  custom['pre[class*="language-"]'] = {
    ...custom['pre[class*="language-"]'],
    background: 'none',
    margin: 0,
    padding: 0,
    fontSize: '13px',
    lineHeight: '1.6',
    color: '#d4e8d4',  // Green-white text matching the UI
  };
  custom['code[class*="language-"]'] = {
    ...custom['code[class*="language-"]'],
    background: 'none',
    fontSize: '13px',
    lineHeight: '1.6',
    color: '#d4e8d4',
  };
  return custom;
}

// ── Props ─────────────────────────────────────────────────────────────────
interface IDECodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  filepath?: string;
  isStreaming?: boolean;
  showLineNumbers?: boolean;
  defaultCollapsed?: boolean;
  maxCollapsedLines?: number;
}

export function IDECodeBlock({
  code,
  language = '',
  filename,
  filepath,
  isStreaming = false,
  showLineNumbers = true,
  defaultCollapsed = false,
  maxCollapsedLines = 35,
}: IDECodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [expanded, setExpanded] = useState(false);
  const [lineCount, setLineCount] = useState(countLines(code));
  const codeRef = useRef<HTMLDivElement>(null);
  const LINE_HEIGHT = 20.8;

  useEffect(() => {
    setLineCount(countLines(code));
  }, [code]);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  const handleToggleExpand = useCallback(() => {
    setExpanded(prev => !prev);
  }, []);

  const langKey = language.toLowerCase();
  const langLabel = LANGUAGE_LABELS[langKey] || langKey.toUpperCase() || 'Plain Text';
  const langStyle = LANG_ICON_COLORS[langKey] || DEFAULT_LANG_STYLE;

  const displayFilename = filename || '';
  const displayPath = filepath || '';
  const headerLabel = displayFilename && displayPath
    ? `${displayFilename} — ${displayPath}`
    : displayFilename
      ? displayFilename
      : langLabel;

  const fileSize = useMemo(() => formatBytes(new Blob([code]).size), [code]);

  const shouldTruncate = !expanded && lineCount > maxCollapsedLines;
  const displayCode = shouldTruncate
    ? code.split('\n').slice(0, maxCollapsedLines).join('\n')
    : code;

  const customStyle = useMemo(() => getCustomStyle(), []);

  return (
    <div className="rounded-lg overflow-hidden border border-[#1a2a1a] my-2 shadow-lg shadow-black/20 font-mono group">
      {/* ── Header Bar — themed green-black ──────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#0a120a] border-b border-[#1a2a1a]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {/* File icon with language color */}
          <div className={`flex items-center justify-center w-5 h-5 rounded shrink-0 ${langStyle.bg} ${langStyle.border} border`}>
            <FileCode2 className={`h-3 w-3 ${langStyle.text}`} />
          </div>

          {/* Filename + path */}
          <div className="flex items-center gap-1.5 min-w-0 truncate">
            <span className="text-[12px] text-[#d4e8d4] font-medium truncate">
              {headerLabel}
            </span>
          </div>

          {/* Language badge */}
          <span className={`text-[10px] px-1.5 py-[1px] rounded font-medium shrink-0 ${langStyle.bg} ${langStyle.text} ${langStyle.border} border`}>
            {langLabel}
          </span>

          {/* Separator */}
          <div className="w-px h-3 bg-[#1a2a1a] shrink-0" />

          {/* File size */}
          <span className="text-[10px] text-[#5a7a5a] shrink-0 flex items-center gap-1">
            <span>{fileSize}</span>
          </span>

          {/* Separator */}
          <div className="w-px h-3 bg-[#1a2a1a] shrink-0" />

          {/* Line count — animated when streaming */}
          <span className="text-[10px] text-[#5a7a5a] shrink-0 flex items-center gap-1">
            <span className={isStreaming ? 'text-[#39d353] animate-pulse' : ''}>
              {lineCount}
            </span>
            <span>lines</span>
            {isStreaming && (
              <span className="inline-block w-1.5 h-3 bg-[#39d353] animate-pulse rounded-[1px]" />
            )}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0 ml-2">
          {/* Expand/collapse toggle */}
          <button
            onClick={handleToggleExpand}
            className="flex items-center justify-center w-6 h-6 rounded hover:bg-[#1a2a1a] text-[#5a7a5a] hover:text-[#d4e8d4] transition-colors"
            title={expanded ? 'Collapse to chat size' : 'Expand to full view'}
          >
            {expanded ? (
              <Shrink className="h-3.5 w-3.5" />
            ) : (
              <Expand className="h-3.5 w-3.5" />
            )}
          </button>

          {/* Copy button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] hover:bg-[#1a2a1a] transition-colors"
            title="Copy code"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-[#39d353]" />
                <span className="text-[#39d353]">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3 text-[#5a7a5a] group-hover:text-[#8ab08a]" />
                <span className="text-[#5a7a5a] group-hover:text-[#8ab08a]">Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Code Area — themed to match deep green-black ─────────────── */}
      <div
        className={`bg-[#080d08] overflow-hidden transition-all duration-200 ${
          expanded ? 'max-h-[80vh]' : ''
        }`}
      >
        <div
          ref={codeRef}
          className="overflow-auto custom-scrollbar-vsc"
          style={{
            maxHeight: expanded ? '80vh' : shouldTruncate ? `${maxCollapsedLines * LINE_HEIGHT + 16}px` : '600px',
          }}
        >
          <div className="flex">
            {/* Line number gutter — themed green-black */}
            {showLineNumbers && (
              <div
                className="sticky left-0 bg-[#080d08] border-r border-[#111a11] z-10 shrink-0"
                aria-hidden="true"
              >
                <div className="py-2">
                  {displayCode.split('\n').map((_, i) => (
                    <div
                      key={i}
                      className="text-[11px] font-mono leading-[1.6] text-[#3a5a3a] hover:text-[#8ab08a] pr-3 pl-3 text-right select-none transition-colors"
                      style={{ minWidth: '3rem' }}
                    >
                      {i + 1}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Syntax highlighted code */}
            <div className="flex-1 min-w-0 py-2 pl-4 pr-4">
              <SyntaxHighlighter
                language={langKey || 'text'}
                style={customStyle}
                showLineNumbers={false}
                wrapLines={true}
                customStyle={{
                  background: 'none',
                  margin: 0,
                  padding: 0,
                  fontSize: '13px',
                  lineHeight: '1.6',
                  color: '#d4e8d4',
                }}
                codeTagProps={{
                  style: {
                    fontSize: '13px',
                    lineHeight: '1.6',
                    fontFamily: 'var(--font-geist-mono), "Cascadia Code", "Fira Code", Consolas, monospace',
                    color: '#d4e8d4',
                  },
                }}
              >
                {displayCode}
              </SyntaxHighlighter>
            </div>
          </div>

          {/* Truncation overlay — themed */}
          {shouldTruncate && (
            <div className="relative">
              <div
                className="absolute bottom-0 left-0 right-0 h-16 pointer-events-none"
                style={{
                  background: 'linear-gradient(to bottom, transparent, #080d08)',
                }}
              />
              <div className="flex items-center justify-center py-2 relative z-10">
                <button
                  onClick={handleToggleExpand}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#111a11] border border-[#1a3a1a] text-[11px] text-[#39d353] hover:bg-[#1a2a1a] hover:text-[#5af75a] transition-colors"
                >
                  <Expand className="h-3 w-3" />
                  <span>Show all {lineCount} lines</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Status Bar — themed green-black ──────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1 bg-[#0a120a] border-t border-[#1a2a1a] text-[10px] text-[#5a7a5a]">
        <div className="flex items-center gap-3">
          <span>{langLabel}</span>
          <span>UTF-8</span>
          <span>LF</span>
        </div>
        <div className="flex items-center gap-3">
          <span>Ln {lineCount}, Col 1</span>
          <span>{fileSize}</span>
          <span>{lineCount} lines</span>
        </div>
      </div>
    </div>
  );
}

// ── Inline Code (for single-line, non-block code) — themed ────────────────
export function InlineCode({ children }: { children: React.ReactNode }) {
  return (
    <code className="font-mono text-[12px] bg-[#0a120a] px-1.5 py-0.5 rounded border border-[#1a2a1a] text-[#7ddf7d]">
      {children}
    </code>
  );
}

export default IDECodeBlock;

import React, { useRef, useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { formatTime, formatBytes } from '../lib/utils'

/* ── Design tokens ───────────────────────────────────────────────────────── */
const C = {
  bg:         '#080b08',
  surface:    '#0d110d',
  surfaceUp:  '#111611',
  surfaceHi:  '#161e16',
  border:     '#1a2a1a',
  borderDim:  '#0f1a0f',
  accent:     '#39d353',
  accentDim:  '#1a3d1a',
  accentMid:  '#27622e',
  amber:      '#e8a420',
  amberDim:   '#2d1f00',
  amberMid:   '#4a3000',
  blue:       '#4a9eff',
  red:        '#e05555',
  textPri:    '#d4e8d4',
  textSec:    '#8ab08a',
  textDim:    '#6a8a6a',
  mono:       '"JetBrains Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
  sans:       '"IBM Plex Sans", system-ui, sans-serif',
}

/* ── Highlight.js dark theme (inline) ───────────────────────────────────── */
const HLJS_CSS = `
/* GitHub Dark Dimmed — adapted for LocalMind green tones */
.hljs { color: #a8d8a8; background: transparent; }
.hljs-comment, .hljs-quote { color: #6a8a6a; font-style: italic; }
.hljs-keyword, .hljs-selector-tag, .hljs-addition { color: #5cb85c; }
.hljs-number, .hljs-string, .hljs-meta .hljs-meta-string, .hljs-literal, .hljs-doctag, .hljs-regexp { color: #7ec87e; }
.hljs-title, .hljs-section, .hljs-name, .hljs-selector-id, .hljs-selector-class { color: #8fd88f; }
.hljs-attribute, .hljs-attr, .hljs-variable, .hljs-template-variable, .hljs-class .hljs-title, .hljs-type { color: #6bc46b; }
.hljs-symbol, .hljs-bullet, .hljs-substitution, .hljs-meta, .hljs-meta .hljs-keyword, .hljs-meta .hljs-built_in { color: #5aa85a; }
.hljs-built_in, .hljs-deletion { color: #e05555; }
.hljs-link { color: #4a9eff; text-decoration: underline; }
.hljs-params { color: #a8d8a8; }
.hljs-emphasis { font-style: italic; }
.hljs-strong { font-weight: bold; }
`

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function useCopy(text) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }, [text])
  return [copied, copy]
}

async function openPath(path, isFolder = false) {
  try {
    await fetch(`/api/${isFolder ? 'open-folder' : 'open-file'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
  } catch (e) {
    console.warn('Could not open path:', e)
  }
}

/* ── FileWriteResult ─────────────────────────────────────────────────────── */
// Renders the "filename - /directory/" output from _do_write as two clickable chips.
// Pattern: "<name> - <absolute-dir>/"
const FILE_WRITE_RE = /^([\w.\-]+) - (\/[^\n]+)\/$|^([\w.\-]+) - ([A-Za-z]:\\[^\n]+)\\$/

function FileWriteResult({ text }) {
  const [fileHov, setFileHov] = useState(false)
  const [dirHov,  setDirHov]  = useState(false)

  // Try both Unix and Windows path formats
  const m = text.match(/^([\w.\-]+) - (.+)\/?\s*$/)
  if (!m) return <span style={{ color: C.textPri }}>{text}</span>

  const filename = m[1]
  const dir = m[2].replace(/\/$/, '')
  const fullPath = `${dir}/${filename}`

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '6px',
      padding: '6px 10px',
      background: C.surfaceHi,
      border: `1px solid ${C.accentMid}`,
      borderRadius: '8px',
      marginTop: '2px',
    }}>
      {/* File chip */}
      <button
        title={`Open ${fullPath}`}
        onMouseEnter={() => setFileHov(true)}
        onMouseLeave={() => setFileHov(false)}
        onClick={() => openPath(fullPath, false)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '5px',
          background: fileHov ? C.accentDim : 'transparent',
          border: `1px solid ${fileHov ? C.accent : C.accentMid}`,
          borderRadius: '5px', padding: '3px 9px',
          cursor: 'pointer', transition: 'all 0.12s',
          fontFamily: C.mono, fontSize: '12px',
          color: fileHov ? C.accent : C.textPri, fontWeight: 500,
        }}
      >
        <span style={{ fontSize: '11px', opacity: 0.7 }}>📄</span>
        {filename}
      </button>
      <span style={{ color: C.textDim, fontSize: '11px', fontFamily: C.mono }}>in</span>
      {/* Directory chip */}
      <button
        title={`Open folder ${dir}`}
        onMouseEnter={() => setDirHov(true)}
        onMouseLeave={() => setDirHov(false)}
        onClick={() => openPath(dir, true)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '5px',
          background: dirHov ? C.amberDim : 'transparent',
          border: `1px solid ${dirHov ? C.amber : '#3a2800'}`,
          borderRadius: '5px', padding: '3px 9px',
          cursor: 'pointer', transition: 'all 0.12s',
          fontFamily: C.mono, fontSize: '11px',
          color: dirHov ? C.amber : C.textSec,
          maxWidth: '260px', overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: '11px', opacity: 0.7 }}>📁</span>
        {dir}/
      </button>
    </div>
  )
}

/* ── Markdown custom component renderers ─────────────────────────────────── */

/** Code block with header bar, language label, and copy button */
function MarkdownCodeBlock({ className, children, ...props }) {
  const match = /language-(\w+)/.exec(className || '')
  const lang = match ? match[1] : ''
  const codeText = String(children).replace(/\n$/, '')
  const [copied, copy] = useCopy(codeText)

  // Detect if this is inline code (no newline) vs block code
  // react-markdown wraps block code in <pre><code> and inline in just <code>
  // We handle this via the pre component below, so this code component
  // only handles the actual <code> rendering inside <pre>
  return (
    <code className={className} {...props}>
      {children}
    </code>
  )
}

/** Pre block wrapper that adds the header bar with language + copy button */
function MarkdownPreBlock({ children, ...props }) {
  // Extract language and text from the child <code> element
  let lang = ''
  let codeText = ''

  if (React.isValidElement(children) && children.props) {
    const codeProps = children.props
    if (codeProps.className) {
      const match = /language-(\w+)/.exec(codeProps.className)
      lang = match ? match[1] : ''
    }
    codeText = String(codeProps.children || '').replace(/\n$/, '')
  } else {
    codeText = String(children).replace(/\n$/, '')
  }

  const [copied, copy] = useCopy(codeText)

  // If there's no language and it's a single line, render as inline code
  if (!lang && !codeText.includes('\n')) {
    return (
      <code style={{
        fontFamily: C.mono, fontSize: '11.5px', background: C.surface,
        padding: '1px 5px', borderRadius: '3px', color: '#8ac88a',
        border: `1px solid ${C.border}`,
      }}>
        {codeText}
      </code>
    )
  }

  return (
    <div style={{
      background: '#040804', border: `1px solid ${C.border}`,
      borderRadius: '6px', overflow: 'hidden', margin: '8px 0',
      fontFamily: C.mono, maxWidth: '100%',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '5px 10px', background: C.surface, borderBottom: `1px solid ${C.border}`,
      }}>
        <span style={{ fontSize: '9px', fontFamily: C.mono, color: C.textDim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          {lang || 'text'}
        </span>
        <button onClick={copy} style={{
          fontSize: '9px', fontFamily: C.mono,
          color: copied ? C.accent : C.textDim,
          background: 'none', border: `1px solid ${copied ? C.accentDim : C.borderDim}`,
          borderRadius: '3px', padding: '2px 6px', cursor: 'pointer', letterSpacing: '0.06em',
        }}>
          {copied ? 'copied' : 'copy'}
        </button>
      </div>
      <pre style={{
        margin: 0, padding: '10px 12px', overflowX: 'auto',
        color: '#a8d8a8', fontSize: '12px', fontFamily: C.mono, lineHeight: 1.6, whiteSpace: 'pre',
        maxWidth: '100%',
      }} {...props}>
        {children}
      </pre>
    </div>
  )
}

/** Inline code styling */
function MarkdownInlineCode({ children, ...props }) {
  return (
    <code style={{
      fontFamily: C.mono, fontSize: '11.5px', background: C.surface,
      padding: '1px 5px', borderRadius: '3px', color: '#8ac88a',
      border: `1px solid ${C.border}`,
    }} {...props}>
      {children}
    </code>
  )
}

/** Styled link that opens in external browser via Electron or new tab */
function MarkdownLink({ href, children, ...props }) {
  const handleClick = useCallback((e) => {
    e.preventDefault()
    if (window.electronAPI?.openExternal) {
      window.electronAPI.openExternal(href)
    } else {
      window.open(href, '_blank', 'noopener,noreferrer')
    }
  }, [href])

  return (
    <a
      href={href}
      onClick={handleClick}
      style={{
        color: C.blue,
        textDecoration: 'underline',
        textDecorationStyle: 'dotted',
        textUnderlineOffset: '2px',
      }}
      title={href}
      {...props}
    >
      {children}
    </a>
  )
}

/** Styled table with dark theme */
function MarkdownTable({ children, ...props }) {
  return (
    <div style={{ overflowX: 'auto', margin: '8px 0' }}>
      <table style={{
        borderCollapse: 'collapse',
        width: '100%',
        fontSize: '12px',
        fontFamily: C.mono,
      }} {...props}>
        {children}
      </table>
    </div>
  )
}

function MarkdownTableHead({ children, ...props }) {
  return (
    <thead style={{ borderBottom: `2px solid ${C.accentMid}` }} {...props}>
      {children}
    </thead>
  )
}

function MarkdownTableRow({ children, ...props }) {
  return (
    <tr style={{ borderBottom: `1px solid ${C.border}` }} {...props}>
      {children}
    </tr>
  )
}

function MarkdownTableCell({ children, isHeader, ...props }) {
  const style = isHeader ? {
    padding: '6px 10px',
    textAlign: 'left',
    fontWeight: 600,
    color: C.accent,
    fontSize: '11px',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    background: C.surface,
  } : {
    padding: '5px 10px',
    color: C.textPri,
  }
  const Tag = isHeader ? 'th' : 'td'
  return <Tag style={style} {...props}>{children}</Tag>
}

/** Styled headings */
function MarkdownHeading({ level, children, ...props }) {
  const sizes = [null, '16px', '14px', '13px', '12px']
  const weights = [null, 680, 640, 600, 600]
  const sz = sizes[level] || '13px'
  const fw = weights[level] || 600
  return (
    <div style={{
      fontSize: sz, fontWeight: fw, color: C.textPri,
      margin: '10px 0 3px', fontFamily: C.sans,
    }} {...props}>
      {children}
    </div>
  )
}

/** Styled unordered list */
function MarkdownUl({ children, ...props }) {
  return (
    <ul style={{
      margin: '4px 0 4px 18px', padding: 0, listStyle: 'disc',
    }} {...props}>
      {children}
    </ul>
  )
}

/** Styled ordered list */
function MarkdownOl({ children, ...props }) {
  return (
    <ol style={{
      margin: '4px 0 4px 18px', padding: 0, listStyle: 'decimal',
    }} {...props}>
      {children}
    </ol>
  )
}

/** Styled list item */
function MarkdownLi({ children, ...props }) {
  return (
    <li style={{ marginBottom: '2px', lineHeight: 1.65, color: C.textPri }} {...props}>
      {children}
    </li>
  )
}

/** Styled paragraph */
function MarkdownP({ children, ...props }) {
  return (
    <p style={{ margin: '2px 0', lineHeight: 1.7, color: C.textPri }} {...props}>
      {children}
    </p>
  )
}

/** Styled blockquote */
function MarkdownBlockquote({ children, ...props }) {
  return (
    <blockquote style={{
      margin: '6px 0', padding: '6px 12px',
      borderLeft: `2px solid ${C.accentDim}`,
      background: C.surface, color: C.textSec,
      borderRadius: '0 4px 4px 0',
    }} {...props}>
      {children}
    </blockquote>
  )
}

/** Styled horizontal rule */
function MarkdownHr({ ...props }) {
  return (
    <hr style={{
      border: 'none', borderTop: `1px solid ${C.border}`, margin: '6px 0',
    }} {...props} />
  )
}

/** Styled strong text */
function MarkdownStrong({ children, ...props }) {
  return <strong style={{ color: C.textPri, fontWeight: 650 }} {...props}>{children}</strong>
}

/** Styled emphasis text */
function MarkdownEm({ children, ...props }) {
  return <em style={{ color: C.textSec }} {...props}>{children}</em>
}

/** Styled strikethrough (from remark-gfm) */
function MarkdownDel({ children, ...props }) {
  return <del style={{ color: C.textDim, textDecoration: 'line-through' }} {...props}>{children}</del>
}

/* ── MarkdownContent ─────────────────────────────────────────────────────── */
function MarkdownContent({ text }) {
  if (!text) return null

  // Check for file write result: "filename - /path/to/dir/"
  const fwMatch = text.trim().match(/^([\w.\-]+) - (.+\/?)$/)
  if (fwMatch) return <FileWriteResult text={text.trim()} />

  return (
    <>
      <style>{HLJS_CSS}</style>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code: ({ node, inline, className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '')
            // If it has a language class or contains a newline, it's a block code
            if (!inline && (match || String(children).includes('\n'))) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              )
            }
            // Inline code
            return (
              <code style={{
                fontFamily: C.mono, fontSize: '11.5px', background: C.surface,
                padding: '1px 5px', borderRadius: '3px', color: '#8ac88a',
                border: `1px solid ${C.border}`,
              }} {...props}>
                {children}
              </code>
            )
          },
          pre: MarkdownPreBlock,
          a: MarkdownLink,
          table: MarkdownTable,
          thead: MarkdownTableHead,
          tr: MarkdownTableRow,
          th: ({ children, ...props }) => <MarkdownTableCell isHeader {...props}>{children}</MarkdownTableCell>,
          td: ({ children, ...props }) => <MarkdownTableCell {...props}>{children}</MarkdownTableCell>,
          h1: ({ children, ...props }) => <MarkdownHeading level={1} {...props}>{children}</MarkdownHeading>,
          h2: ({ children, ...props }) => <MarkdownHeading level={2} {...props}>{children}</MarkdownHeading>,
          h3: ({ children, ...props }) => <MarkdownHeading level={3} {...props}>{children}</MarkdownHeading>,
          h4: ({ children, ...props }) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          h5: ({ children, ...props }) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          h6: ({ children, ...props }) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          ul: MarkdownUl,
          ol: MarkdownOl,
          li: MarkdownLi,
          p: MarkdownP,
          blockquote: MarkdownBlockquote,
          hr: MarkdownHr,
          strong: MarkdownStrong,
          em: MarkdownEm,
          del: MarkdownDel,
        }}
      >
        {text}
      </ReactMarkdown>
    </>
  )
}

/* ── ThinkingBlock ───────────────────────────────────────────────────────── */
function ThinkingBlock({ text, pending, durationMs }) {
  const [open, setOpen] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (pending) {
      const start = Date.now()
      timerRef.current = setInterval(() => setElapsed(Date.now() - start), 300)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [pending])

  useEffect(() => {
    if (!pending && text) { const t = setTimeout(() => setOpen(false), 700); return () => clearTimeout(t) }
  }, [pending, text])

  if (!pending && !text) return null

  const ms = pending ? elapsed : durationMs
  const timeStr = ms >= 60000 ? `${Math.round(ms/60000)}m` : ms >= 1000 ? `${(ms/1000).toFixed(1)}s` : `${Math.round(ms/100)*100}ms`
  const label = pending ? `thinking ${timeStr}` : `thought for ${timeStr}`

  return (
    <div style={{ marginBottom: '8px' }}>
      <button
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '6px',
          fontSize: '11px', fontFamily: C.mono,
          color: pending ? C.accent : C.textSec,
          cursor: 'pointer', background: 'none', border: 'none',
          padding: '2px 0', fontStyle: pending ? 'italic' : 'normal',
        }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ color: pending ? C.accent : C.textDim, fontSize: '10px' }}>
          {pending ? '◉' : (open ? '▾' : '▸')}
        </span>
        <span>{label}</span>
        {!open && text && <span style={{ color: C.textDim, fontSize: '10px' }}>— {text.trim().slice(0,55)}{text.length>55?'…':''}</span>}
      </button>
      {open && (
        <div style={{
          marginTop: '6px', padding: '8px 12px',
          background: C.surface, border: `1px solid ${C.border}`,
          borderLeft: `2px solid ${C.accentDim}`, borderRadius: '0 4px 4px 0',
          fontSize: '12px', fontFamily: C.mono, color: C.textSec,
          lineHeight: 1.65, whiteSpace: 'pre-wrap',
          maxHeight: '200px', overflowY: 'auto',
        }}>
          {text || <span style={{ color: C.textDim }}>waiting…</span>}
        </div>
      )}
    </div>
  )
}

/* ── ToolSteps ───────────────────────────────────────────────────────────── */
function ToolSteps({ steps }) {
  if (!steps?.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginBottom: '8px' }}>
      {steps.map((s, i) => (
        <span key={i} style={{
          display: 'inline-flex', alignItems: 'center', gap: '5px',
          fontSize: '10px', fontFamily: C.mono,
          color: s.status === 'failed' ? C.red : s.status === 'running' ? C.amber : C.textSec,
          background: C.surface,
          border: `1px solid ${s.status === 'failed' ? '#3d1515' : s.status === 'running' ? '#3d2200' : C.border}`,
          borderRadius: '4px', padding: '2px 8px',
        }}>
          <span style={{
            width: '5px', height: '5px', borderRadius: '50%', flexShrink: 0,
            background: s.status === 'failed' ? C.red : s.status === 'running' ? C.amber : C.textSec,
          }} />
          {s.action}
          {s.input && <span style={{ color: C.textDim }}>:{s.input.slice(0,40)}</span>}
        </span>
      ))}
    </div>
  )
}

/* ── ConfirmationPrompt ──────────────────────────────────────────────────── */
function ConfirmationPrompt({ confirmation, onConfirm }) {
  const [hovered, setHovered] = React.useState(null)
  const btnBase = {
    padding: '6px 18px', borderRadius: '6px', border: 'none',
    cursor: 'pointer', fontSize: '12px', fontFamily: C.mono,
    fontWeight: 600, letterSpacing: '0.05em', transition: 'opacity 0.15s',
  }
  return (
    <div style={{
      marginTop: '10px', padding: '12px 14px', borderRadius: '10px',
      border: `1px solid ${C.border}`, background: C.surface,
    }}>
      <div style={{ fontSize: '10px', color: C.textDim, fontFamily: C.mono, marginBottom: '5px', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
        write to disk
      </div>
      <div style={{ fontSize: '12px', color: C.textPri, fontFamily: C.mono, marginBottom: '10px', wordBreak: 'break-all' }}>
        {confirmation.path}
      </div>
      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          style={{ ...btnBase, background: C.accent, color: '#000', opacity: hovered === 'accept' ? 0.85 : 1 }}
          onMouseEnter={() => setHovered('accept')} onMouseLeave={() => setHovered(null)}
          onClick={() => onConfirm(true)}
        >Accept</button>
        <button
          style={{ ...btnBase, background: 'transparent', color: C.textSec, border: `1px solid ${C.border}`, opacity: hovered === 'reject' ? 0.7 : 1 }}
          onMouseEnter={() => setHovered('reject')} onMouseLeave={() => setHovered(null)}
          onClick={() => onConfirm(false)}
        >Reject</button>
      </div>
    </div>
  )
}

/* ── MessageBubble ───────────────────────────────────────────────────────── */
function MessageBubble({ msg, onConfirm }) {
  const [hovered, setHovered] = useState(false)
  const [copied, copy] = useCopy(msg.content || '')
  const isUser = msg.role === 'user'

  const bubbleStyle = isUser ? {
    maxWidth: '78%',
    alignSelf: 'flex-end',
    background: C.amberDim,
    border: `1px solid ${C.amberMid}`,
    borderRadius: '14px 14px 3px 14px',
    padding: '10px 14px',
    position: 'relative',
    overflow: 'hidden',
  } : {
    maxWidth: '86%',
    alignSelf: 'flex-start',
    background: C.surfaceUp,
    border: `1px solid ${C.border}`,
    borderRadius: '14px 14px 14px 3px',
    padding: '10px 14px',
    position: 'relative',
    overflow: 'hidden',
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        padding: '2px 20px',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Role label + timestamp — outside bubble */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        marginBottom: '4px',
        flexDirection: isUser ? 'row-reverse' : 'row',
      }}>
        <span style={{
          fontSize: '10px', fontFamily: C.mono, fontWeight: 700,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: isUser ? C.amber : C.accent,
        }}>
          {isUser ? 'you' : 'localmind'}
        </span>
        <span style={{ fontSize: '10px', fontFamily: C.mono, color: C.textDim }}>
          {formatTime(msg.timestamp || Date.now() / 1000)}
        </span>
        {msg.file && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '10px', fontFamily: C.mono, color: C.textSec,
            background: C.surface, border: `1px solid ${C.border}`,
            borderRadius: '3px', padding: '1px 6px',
            maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={msg.filePath || msg.file}>
            ⊞ {msg.file}{msg.fileSize ? ` · ${formatBytes(msg.fileSize)}` : ''}
          </span>
        )}
      </div>

      {/* Bubble */}
      <div style={bubbleStyle}>
        {isUser ? (
          <div style={{ color: '#f5e0a0', fontSize: '14px', lineHeight: 1.65, fontFamily: C.sans }}>
            {msg.content}
          </div>
        ) : (
          <>
            {msg.isAgent && (msg.thinking || (msg.pending && !msg.content)) && (
              <ThinkingBlock text={msg.thinking} pending={msg.pending} durationMs={msg.thinkMs || 0} />
            )}
            <ToolSteps steps={msg.toolSteps} />
            {msg.confirmation && onConfirm && (
              <ConfirmationPrompt
                confirmation={msg.confirmation}
                onConfirm={(accept) => onConfirm(msg.id, accept)}
              />
            )}
            {(msg.content || msg.error) && (
              <div style={{ color: C.textPri, fontSize: '14px', lineHeight: 1.7, fontFamily: C.sans, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                {msg.error
                  ? <span style={{ color: C.red }}>error: {msg.content}</span>
                  : <MarkdownContent text={msg.content} />
                }
                {msg.pending && !msg.error && (
                  <span style={{
                    display: 'inline-block', width: '7px', height: '13px',
                    background: C.accent, marginLeft: '2px', verticalAlign: 'middle',
                    borderRadius: '1px', animation: 'lm-blink 1s step-end infinite',
                  }} />
                )}
              </div>
            )}
            {!msg.pending && !msg.content && !msg.thinking && !msg.toolSteps?.length && msg.pending === false && (
              <span style={{ color: C.textDim, fontSize: '12px', fontFamily: C.mono }}>_</span>
            )}
          </>
        )}
      </div>

      {/* Copy action — appears on hover below the bubble */}
      {!isUser && !msg.pending && msg.content && (
        <div style={{
          marginTop: '4px',
          opacity: hovered ? 1 : 0,
          transition: 'opacity 0.15s',
        }}>
          <button onClick={copy} style={{
            fontSize: '9px', fontFamily: C.mono, color: C.textDim,
            background: 'none', border: `1px solid ${C.borderDim}`,
            borderRadius: '3px', padding: '2px 7px', cursor: 'pointer',
            letterSpacing: '0.06em', textTransform: 'uppercase',
          }}>
            {copied ? '✓ copied' : 'copy'}
          </button>
        </div>
      )}
    </div>
  )
}

/* ── MessageList ─────────────────────────────────────────────────────────── */
export function MessageList({ messages, onConfirm }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: '20px', padding: '40px', fontFamily: C.mono,
      }}>
        <style>{`
          @keyframes lm-blink { 50% { opacity: 0 } }
          @keyframes lm-pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        `}</style>
        <pre style={{
          color: C.accentDim, fontSize: '11px', lineHeight: 1.5,
          whiteSpace: 'pre', letterSpacing: '0.05em',
        }}>{`  ╔══════════════╗\n  ║  LOCAL MIND  ║\n  ╚══════════════╝`}</pre>
        <span style={{ fontSize: '12px', color: C.textDim, letterSpacing: '0.12em', textTransform: 'uppercase' }}>ready</span>
        <span style={{ fontSize: '11px', color: C.textDim, fontFamily: C.mono, textAlign: 'center', lineHeight: 1.7 }}>
          {'local inference · no cloud · no logs\n'}
          {'type a message or attach a file'}
        </span>
      </div>
    )
  }

  // Group consecutive messages by role to add spacing between role-changes
  const grouped = messages.reduce((acc, msg, i) => {
    const prev = messages[i - 1]
    const isFirst = !prev || prev.role !== msg.role
    acc.push({ msg, isFirst })
    return acc
  }, [])

  return (
    <div style={{
      flex: 1, overflowY: 'auto', padding: '12px 0 8px',
      display: 'flex', flexDirection: 'column', gap: '2px',
      scrollbarWidth: 'thin', scrollbarColor: `${C.border} transparent`,
    }}>
      <style>{`
        @keyframes lm-blink { 50% { opacity: 0 } }
        @keyframes lm-pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
      `}</style>
      {grouped.map(({ msg, isFirst }) => (
        <div key={msg.id} style={{ marginTop: isFirst ? '12px' : '2px' }}>
          <MessageBubble msg={msg} onConfirm={onConfirm} />
        </div>
      ))}
      <div ref={bottomRef} style={{ height: '8px' }} />
    </div>
  )
}

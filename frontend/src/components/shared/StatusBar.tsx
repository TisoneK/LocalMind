import { useState, useEffect } from 'react'
// SettingsModal import removed - component needs to be created

const C = {
  bg:    '#050805',
  border:'#121a12',
  accent:'#39d353',
  amber: '#e8a420',
  dim:   '#6a8a6a',
  muted: '#8ab08a',
  mono:  '"JetBrains Mono","Fira Code","Cascadia Code",ui-monospace,monospace',
}

const S = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: '0',
    height: '32px',
    background: C.bg,
    borderBottom: `1px solid ${C.border}`,
    fontFamily: C.mono,
    fontSize: '11px',
    flexShrink: 0,
    overflow: 'hidden',
  },
  seg: {
    display: 'flex',
    alignItems: 'center',
    gap: '7px',
    padding: '0 14px',
    height: '100%',
    borderRight: `1px solid ${C.border}`,
    whiteSpace: 'nowrap',
  },
  dot: (ok) => ({
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background: ok ? C.accent : '#e05555',
    boxShadow: ok ? `0 0 5px ${C.accent}80` : 'none',
    flexShrink: 0,
  }),
  status: (ok) => ({
    color: ok ? C.accent : '#e05555',
    letterSpacing: '0.08em',
  }),
  model: {
    color: C.amber,
    letterSpacing: '0.05em',
  },
  spacer: { flex: 1 },
  title: {
    color: C.muted,
    letterSpacing: '0.05em',
    maxWidth: '300px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    padding: '0 14px',
    cursor: 'default',
  },
  iconBtn: {
    height: '100%',
    padding: '0 14px',
    background: 'transparent',
    border: 'none',
    borderLeft: `1px solid ${C.border}`,
    color: C.dim,
    fontFamily: C.mono,
    fontSize: '13px',
    cursor: 'pointer',
    transition: 'color 0.15s',
    lineHeight: 1,
  },
  newBtn: {
    height: '100%',
    padding: '0 14px',
    background: 'transparent',
    border: 'none',
    borderLeft: `1px solid ${C.border}`,
    color: C.dim,
    fontFamily: C.mono,
    fontSize: '11px',
    letterSpacing: '0.08em',
    cursor: 'pointer',
    transition: 'color 0.15s',
  },
  winBtn: {
    height: '100%',
    padding: '0 13px',
    background: 'transparent',
    border: 'none',
    borderLeft: `1px solid ${C.border}`,
    color: C.dim,
    fontFamily: C.mono,
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'color 0.15s, background 0.15s',
    lineHeight: 1,
    userSelect: 'none',
  },
}

export function StatusBar({ onNewChat, sessionId, health, sessionTitle }) {
  const [showSettings, setShowSettings] = useState(false)
  const [isMaximized, setIsMaximized] = useState(false)
  const isElectron = !!window.electronAPI

  useEffect(() => {
    if (!isElectron) return
    // Keep maximize icon in sync when the user resizes via OS controls
    const handler = () => setIsMaximized(window.outerWidth === screen.availWidth && window.outerHeight === screen.availHeight)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [isElectron])

  const ok    = health?.ollama_reachable === true
  const model = health?.model || '---'
  // Clean up model name: remove internal suffixes like " - zen", provider prefixes, etc.
  const displayModel = model
    .replace(/\s*-\s*zen$/i, '')
    .replace(/\s*-\s*local$/i, '')
    .replace(/^ollama[:\/]/, '')
    .trim();
  const label = health == null ? 'connecting' : ok ? 'online' : 'offline'
  const title = sessionTitle || (sessionId ? sessionId.slice(0, 10) : null)

  return (
    <>
      <div style={S.bar}>
        <div style={S.seg}>
          <div style={S.dot(ok)} />
          <span style={S.status(ok)}>{label}</span>
        </div>
        {ok && (
          <div style={S.seg}>
            <span style={S.model}>{displayModel}</span>
          </div>
        )}
        <div style={S.spacer} />
        {title && <span style={S.title} title={title}>{title}</span>}
        <button
          style={S.iconBtn}
          onClick={() => setShowSettings(true)}
          onMouseEnter={e => e.target.style.color = C.accent}
          onMouseLeave={e => e.target.style.color = C.dim}
          title="Settings"
        >
          ⚙
        </button>
        <button
          style={S.newBtn}
          onClick={onNewChat}
          onMouseEnter={e => e.target.style.color = C.accent}
          onMouseLeave={e => e.target.style.color = C.dim}
        >
          + new
        </button>

        {isElectron && <>
          <button
            style={S.winBtn}
            onClick={() => window.electronAPI.minimizeWindow()}
            onMouseEnter={e => e.currentTarget.style.color = C.accent}
            onMouseLeave={e => e.currentTarget.style.color = C.dim}
            title="Minimize"
          >─</button>
          <button
            style={S.winBtn}
            onClick={() => {
              window.electronAPI.maximizeWindow()
              setIsMaximized(v => !v)
            }}
            onMouseEnter={e => e.currentTarget.style.color = C.accent}
            onMouseLeave={e => e.currentTarget.style.color = C.dim}
            title={isMaximized ? 'Restore' : 'Maximize'}
          >{isMaximized ? '❐' : '□'}</button>
          <button
            style={S.winBtn}
            onClick={() => window.electronAPI.closeWindow()}
            onMouseEnter={e => { e.currentTarget.style.color = '#fff'; e.currentTarget.style.background = '#c0392b' }}
            onMouseLeave={e => { e.currentTarget.style.color = C.dim; e.currentTarget.style.background = 'transparent' }}
            title="Close"
          >✕</button>
        </>}
      </div>

      {/* {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />} */}
    </>
  )
}

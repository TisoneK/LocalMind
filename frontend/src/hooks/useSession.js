import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchSessions } from '../lib/api'

/**
 * useSession — centralized session state machine.
 *
 * States:
 *   "new"      — user is in a fresh, unsaved chat (no session selected)
 *   "active"   — user is chatting in a known session
 *   "loading"  — history is being fetched for a selected session
 *
 * Rules:
 *   - App always opens in "new" state (no auto-selection of last session)
 *   - Deleting the active session always transitions back to "new"
 *   - Clicking a session transitions to "active" for that session
 *   - New Chat button always transitions to "new"
 *   - Sessions list refresh NEVER changes the active session
 */
export function useSession() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Track whether we've done the initial fetch so we don't double-load
  const initialFetchDone = useRef(false)

  const loadSessions = useCallback(() => {
    setLoading(true)
    let cancelled = false
    let retryTimer = null

    function attempt(delay = 0) {
      retryTimer = setTimeout(() => {
        if (cancelled) return
        fetchSessions()
          .then((data) => {
            if (cancelled) return
            setSessions(Array.isArray(data) ? data : [])
            setLoading(false)
          })
          .catch((err) => {
            if (cancelled) return
            // Retry with backoff while backend is starting up (max 4s interval)
            const next = Math.min((delay || 500) * 2, 4000)
            setError(err?.message || 'Failed to load sessions')
            attempt(next)
          })
      }, delay)
    }

    attempt()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [])

  useEffect(() => {
    if (!initialFetchDone.current) {
      initialFetchDone.current = true
      loadSessions()
    }
  }, [loadSessions])

  const getSessionTitle = useCallback((sessionId) => {
    const session = sessions.find(s => s.id === sessionId)
    return session?.title || null
  }, [sessions])

  return {
    sessions,
    loading,
    error,
    getSessionTitle,
    refreshSessions: loadSessions,
  }
}

import { useState, useEffect, useRef } from 'react'
import { fetchHealth } from '../lib/api'

// Reduced polling intervals to save data on limited plans
const POLL_INTERVAL_MS = 5000      // 5s during startup (was 1.5s)
const POLL_TIMEOUT_MS  = 120000
const SLOW_REFRESH_MS  = 120000   // 2min after ready (was 60s)

/**
 * useHealth — polls /api/health until engine_ready=true, then stops.
 *
 * After the engine is ready, it does a single slow refresh every 60s to keep
 * the StatusBar status indicator current, instead of polling every 1.5s forever.
 *
 * Returns:
 *   engineReady  {bool}   — true once startup() has fully completed
 *   health       {object} — last successful health payload
 *   error        {string} — set if polling times out
 */
export function useHealth() {
  const [engineReady, setEngineReady] = useState(false)
  const [health, setHealth]           = useState(null)
  const [error, setError]             = useState(null)

  const timerRef     = useRef(null)
  const startedAt    = useRef(Date.now())
  const cancelledRef = useRef(false)

  useEffect(() => {
    cancelledRef.current = false

    async function poll() {
      if (cancelledRef.current) return
      try {
        const data = await fetchHealth()
        if (cancelledRef.current) return
        setHealth(data)
        if (data.engine_ready) {
          setEngineReady(true)
          // FIX: Don't stop polling entirely — switch to a slow 60s refresh
          // so the StatusBar still shows current Ollama reachability.
          // Previously this returned and never polled again, but the StatusBar
          // needs fresh health data to show online/offline status.
          timerRef.current = setTimeout(poll, SLOW_REFRESH_MS)
          return
        }
      } catch (_) {
        // Server still booting — swallow network errors and keep polling
      }

      if (Date.now() - startedAt.current > POLL_TIMEOUT_MS) {
        if (!cancelledRef.current) {
          setError('Server did not become ready within 2 minutes. Check Ollama is running.')
        }
        return
      }

      timerRef.current = setTimeout(poll, POLL_INTERVAL_MS)
    }

    poll()
    return () => {
      cancelledRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return { engineReady, health, error }
}

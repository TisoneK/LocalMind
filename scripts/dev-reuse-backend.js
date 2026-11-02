#!/usr/bin/env node
/**
 * Watcher for a REUSED LocalMind backend (dev-full's reuse path).
 *
 * When scripts/dev-full.js finds a healthy LocalMind already serving on the
 * preferred port, it does not spawn a second instance — this watcher takes the
 * backend slot instead. It exits non-zero when the reused backend stops
 * responding, so `concurrently --kill-others-on-fail` tears the dev stack down
 * exactly as it would if a spawned backend had died. Without this, a reused
 * backend dying silently would leave a frontend and an Electron window talking
 * to nothing.
 *
 * Env: LOCALMIND_HOST (default 127.0.0.1), LOCALMIND_PORT (default 8000).
 */

const http = require('http');

const HOST = process.env.LOCALMIND_HOST || '127.0.0.1';
const PORT = parseInt(process.env.LOCALMIND_PORT || '8000', 10) || 8000;
const POLL_MS = 2000;
const STARTUP_GRACE_MS = 15000; // time to observe the first healthy response
const CONSECUTIVE_FAILURES_TO_FAIL = 3;

function checkHealth() {
  return new Promise((resolve) => {
    const req = http.get(`http://${HOST}:${PORT}/api/health`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          resolve(res.statusCode === 200 && (data.status === 'ok' || data.status === 'degraded'));
        } catch (_) {
          resolve(false);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1500, () => { req.destroy(); resolve(false); });
  });
}

async function main() {
  const startedAt = Date.now();
  let seenHealthy = false;
  let failures = 0;

  console.log(`[watching] the reused LocalMind backend on ${HOST}:${PORT}`);

  for (;;) {
    const healthy = await checkHealth();
    if (healthy) {
      if (!seenHealthy) {
        seenHealthy = true;
        console.log(`[reused] is healthy on ${HOST}:${PORT}`);
      }
      failures = 0;
    } else if (!seenHealthy) {
      if (Date.now() - startedAt > STARTUP_GRACE_MS) {
        console.error(`[none] LocalMind found on ${HOST}:${PORT} — nothing to reuse. Shutting the dev stack down.`);
        process.exit(1);
      }
    } else {
      failures += 1;
      if (failures >= CONSECUTIVE_FAILURES_TO_FAIL) {
        console.error(`[reused] LocalMind backend on ${HOST}:${PORT} stopped responding (${failures} failed probes) — shutting the dev stack down.`);
        process.exit(1);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

main().catch((err) => {
  console.error('[watcher]:', err && err.message ? err.message : err);
  process.exit(1);
});

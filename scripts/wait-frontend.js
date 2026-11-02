#!/usr/bin/env node
/**
 * Wait for the LocalMind frontend dev server — the env-aware replacement for
 * the hardcoded `wait-on http://localhost:3000` in the Electron dev scripts.
 *
 * Polls until the Vite dev server answers on LOCALMIND_FRONTEND_PORT
 * (default 3000); exits non-zero on timeout so the caller fails loudly
 * instead of opening a window at a URL nothing serves.
 */

const http = require('http');

const PORT = parseInt(process.env.LOCALMIND_FRONTEND_PORT || '3000', 10) || 3000;
const TIMEOUT_MS = 60000;
const POLL_MS = 500;

function probe() {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path: '/', timeout: 1500 }, (res) => {
      res.resume(); // any HTTP response means the dev server is serving
      resolve(true);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function main() {
  const deadline = Date.now() + TIMEOUT_MS;
  for (;;) {
    if (await probe()) {
      console.log(`[electron] frontend is serving on http://localhost:${PORT}`);
      process.exit(0);
    }
    if (Date.now() > deadline) {
      console.error(`[electron] frontend did not come up on http://localhost:${PORT} within ${TIMEOUT_MS / 1000}s`);
      process.exit(1);
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

main();

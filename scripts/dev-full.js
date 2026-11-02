#!/usr/bin/env node
/**
 * LocalMind dev orchestrator — the `dev:full` entrypoint (npm start).
 *
 * Ports are a contract read from the environment, never a hardcode:
 *   LOCALMIND_HOST            backend bind host      (default 127.0.0.1)
 *   LOCALMIND_PORT            backend port           (default 8000)
 *   LOCALMIND_FRONTEND_PORT   Vite dev server port   (default 3000)
 *   LOCALMIND_PORT_STRICT=1   never move or reuse — report the conflict and exit 42
 *
 * Conflict policy, resolved BEFORE anything spawns (the old behavior — one
 * foreign app on port 8000 killing the whole tree via --kill-others-on-fail —
 * is the failure this exists to prevent):
 *   - preferred port free                    -> use it
 *   - held by a healthy LocalMind backend    -> reuse it (no second instance;
 *     scripts/dev-reuse-backend.js watches it and tears the stack down if it dies)
 *   - held by a different application        -> strict? report + exit 42
 *                                              : move to the next free port, loudly
 * The chosen ports are propagated to every consumer through env, so the Vite
 * proxy, Electron, the backend bind and the browser CORS checks can never
 * drift apart.
 *
 * Flags:
 *   --print-plan    resolve ports and print the plan without starting anything
 *   --no-electron   start backend + frontend only (browser-only dev, CI)
 */

const { spawn } = require('child_process');
const http = require('http');
const net = require('net');
const path = require('path');
const fs = require('fs');

const projectRoot = path.resolve(__dirname, '..');
process.chdir(projectRoot);

// ── Environment contract ────────────────────────────────────────────────────

function envInt(name, fallback) {
  const raw = parseInt(process.env[name] || '', 10);
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

const HOST = process.env.LOCALMIND_HOST || '127.0.0.1';
const PREFERRED_BACKEND_PORT = envInt('LOCALMIND_PORT', 8000);
const PREFERRED_FRONTEND_PORT = envInt('LOCALMIND_FRONTEND_PORT', 3000);
const STRICT = process.env.LOCALMIND_PORT_STRICT === '1';

// ── Probes ──────────────────────────────────────────────────────────────────

function portResponds(port, host, timeoutMs = 750) {
  // A hard timer race, not socket.setTimeout: an idle timeout does not
  // reliably fire while a connect is still in progress, and a hung connect
  // (a listener whose backlog is full, or a dropped SYN) must count as BUSY,
  // never as free — a false "free" would send the orchestrator at a port it
  // cannot bind.
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;
    const done = (result) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(result);
    };
    const timer = setTimeout(() => done(true), timeoutMs);
    socket.once('connect', () => { clearTimeout(timer); done(true); });
    socket.once('error', () => { clearTimeout(timer); done(false); });
    socket.connect(port, host);
  });
}

function backendIsHealthy(host, port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(`http://${host}:${port}/api/health`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode !== 200) return resolve(false);
        try {
          const data = JSON.parse(body);
          // 'degraded' still means the server is serving (engine warming up).
          resolve(data.status === 'ok' || data.status === 'degraded');
        } catch (_) {
          resolve(false);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(timeoutMs, () => { req.destroy(); resolve(false); });
  });
}

async function findFreePort(startPort, host, attempts = 50) {
  for (let candidate = startPort; candidate < startPort + attempts; candidate++) {
    if (!(await portResponds(candidate, host))) return candidate;
  }
  return null;
}

// ── Resolution ──────────────────────────────────────────────────────────────

/**
 * Resolve one service's port. Returns { port, action } where action is one of
 * 'use' | 'reuse' | 'moved' — or throws { exitCode: 42 } under LOCALMIND_PORT_STRICT.
 */
async function resolveServicePort(kind, preferred, host, { isBackend }) {
  const where = `${host}:${preferred}`;
  if (!(await portResponds(preferred, host))) {
    console.log(`[ports] ${kind.padEnd(9)} ${where}  free — using it`);
    return { port: preferred, action: 'use' };
  }
  if (isBackend && (await backendIsHealthy(host, preferred))) {
    console.log(`[ports] ${kind.padEnd(9)} ${where}  held by a healthy LocalMind — reusing it (no second instance)`);
    return { port: preferred, action: 'reuse' };
  }
  if (STRICT) {
    console.error(`[ports] ${kind.padEnd(9)} ${where}  held by another ${isBackend ? 'application (no healthy LocalMind found there)' : 'application'} — LOCALMIND_PORT_STRICT=1 is set, refusing to move. Free the port and try again.`);
    const err = new Error('strict port conflict');
    err.exitCode = 42;
    throw err;
  }
  const moved = await findFreePort(preferred + 1, host);
  if (!moved) {
    console.error(`[ports] ${kind.padEnd(9)} no free port found between ${preferred + 1} and ${preferred + 50} — giving up.`);
    const err = new Error('no free port');
    err.exitCode = 42;
    throw err;
  }
  console.log(`[ports] ${kind.padEnd(9)} ${where}  held by another ${isBackend ? 'application (no healthy LocalMind found there)' : 'application'} — moving to ${moved} (pin it with ${isBackend ? 'LOCALMIND_PORT' : 'LOCALMIND_FRONTEND_PORT'})`);
  return { port: moved, action: 'moved' };
}

// ── Entrypoint ──────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const printPlan = args.includes('--print-plan');
  const withElectron = !args.includes('--no-electron');

  const backend = await resolveServicePort('backend', PREFERRED_BACKEND_PORT, HOST, { isBackend: true });
  const frontend = await resolveServicePort('frontend', PREFERRED_FRONTEND_PORT, HOST, { isBackend: false });

  const backendUrlHost = HOST === '0.0.0.0' ? 'localhost' : HOST;
  const backendHealth = `http-get://${backendUrlHost}:${backend.port}/api/health`;

  // The env every child inherits — the single source of truth for this run.
  // npm run injects node_modules/.bin into PATH; running the orchestrator
  // directly must do the same, or the spawned slots can't find wait-on /
  // cross-env / vite.
  const env = {
    ...process.env,
    PATH: `${path.join(projectRoot, 'node_modules', '.bin')}${path.delimiter}${process.env.PATH || ''}`,
    LOCALMIND_HOST: HOST,
    LOCALMIND_PORT: String(backend.port),
    LOCALMIND_FRONTEND_PORT: String(frontend.port),
  };

  console.log('');
  console.log(`[ports] Backend  http://localhost:${backend.port}/api/docs${backend.action === 'reuse' ? '  (existing instance)' : ''}`);
  console.log(`[ports] Frontend http://localhost:${frontend.port}/`);
  if (backend.action === 'moved' || frontend.action === 'moved') {
    console.log('[ports] Defaults were taken — set LOCALMIND_PORT / LOCALMIND_FRONTEND_PORT to pin your own.');
  }
  if (printPlan) {
    console.log('[ports] --print-plan: nothing started.');
    return;
  }
  console.log('');

  const slots = [];
  if (backend.action === 'reuse') {
    // Watch the existing instance instead of spawning a second one: if it
    // stops responding, the watcher exits non-zero and the stack tears down.
    slots.push({ name: 'backend', command: 'node scripts/dev-reuse-backend.js', color: 'yellow' });
  } else {
    slots.push({ name: 'backend', command: 'npm run dev:backend', color: 'yellow' });
  }
  slots.push({
    name: 'frontend',
    command: `wait-on -t 60000 ${backendHealth} && npm run dev:frontend`,
    color: 'cyan',
  });
  if (withElectron) {
    slots.push({
      name: 'electron',
      command: `wait-on -t 60000 ${backendHealth} && node scripts/wait-frontend.js && cross-env ELECTRON_DEV_MODE=true npm run dev -w localmind-electron`,
      color: 'green',
    });
  }

  // Locate concurrently through its own package.json `bin` — version-proof,
  // unlike guessing the file layout (v9 moved it to dist/bin/).
  let bin = null;
  try {
    const pkgPath = require.resolve('concurrently/package.json', { paths: [projectRoot] });
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    const rel = pkg.bin && (pkg.bin.concurrently || Object.values(pkg.bin)[0]);
    if (rel) bin = path.join(path.dirname(pkgPath), rel);
  } catch (_) {
    /* not installed — handled below */
  }
  if (!bin || !fs.existsSync(bin)) {
    console.error('[ports] concurrently is not installed — run `npm install` first.');
    process.exit(1);
  }

  const child = spawn(
    process.execPath,
    [
      bin,
      '-n', slots.map((s) => s.name).join(','),
      '-c', slots.map((s) => s.color).join(','),
      '--kill-others-on-fail',
      ...slots.map((s) => s.command),
    ],
    { stdio: 'inherit', env },
  );

  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => child.kill(sig));
  }
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 0);
  });
}

main().catch((err) => {
  if (err && err.exitCode) process.exit(err.exitCode);
  console.error('[ports] unexpected failure:', err && err.message ? err.message : err);
  process.exit(1);
});

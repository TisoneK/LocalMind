#!/usr/bin/env node
/**
 * Cross-platform backend launcher for LocalMind.
 *
 * The venv Python path differs by OS:
 *   Windows:  backend\.venv\Scripts\python.exe
 *   macOS/Linux:  backend/.venv/bin/python
 *
 * The old npm script hardcoded the Windows path, breaking macOS/Linux.
 * This script detects the platform and spawns the correct binary.
 */
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')

const isWin = process.platform === 'win32'
const venvPython = isWin
  ? path.join('backend', '.venv', 'Scripts', 'python.exe')
  : path.join('backend', '.venv', 'bin', 'python')

const serverPath = path.join('backend', 'server.py')

// Helpful error if the venv doesn't exist yet
if (!fs.existsSync(venvPython)) {
  console.error(`\n[dev:backend] Python not found at: ${venvPython}`)
  console.error(`\nMake sure you've created the backend venv:`)
  console.error(`  cd backend`)
  console.error(`  python -m venv .venv`)
  if (isWin) {
    console.error(`  .venv\\Scripts\\activate`)
  } else {
    console.error(`  source .venv/bin/activate`)
  }
  console.error(`  pip install -e ".[dev]"\n`)
  process.exit(1)
}

const child = spawn(venvPython, [serverPath], {
  stdio: 'inherit',
  cwd: process.cwd(),
  env: process.env,
})

child.on('error', (err) => {
  console.error(`[dev:backend] Failed to start backend: ${err.message}`)
  process.exit(1)
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
  } else {
    process.exit(code ?? 0)
  }
})

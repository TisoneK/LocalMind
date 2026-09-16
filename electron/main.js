/**
 * LocalMind Electron Main Process
 *
 * - Creates BrowserWindow that loads UI (Vite dev server or built dist)
 * - Starts Python FastAPI backend as child process
 * - Waits for backend /api/health before showing window
 * - System tray with Show Window / Restart Backend / Quit
 * - Minimize-to-tray on window close
 * - IPC handlers for file dialogs, shell.openPath, backend restart, etc.
 * - Auto-restart backend on crash
 */

const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
  Tray,
  Menu,
  nativeImage,
} = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const isDev = !app.isPackaged;

// The project root is one directory above electron/
const projectRoot = isDev
  ? path.resolve(__dirname, '..')
  : path.resolve(process.resourcesPath, 'app');

const serverScript = path.join(projectRoot, 'backend', 'server.py');

// In dev mode the Vite dev server serves the UI on localhost:3000.
// In production the built files live in frontend/dist/ (relative to project root).
const devServerUrl = 'http://localhost:3000';
const prodIndexPath = path.join(projectRoot, 'frontend', 'dist', 'index.html');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let isQuitting = false;
let backendRestartTimer = null;
let backendStatus = 'stopped'; // stopped | starting | ready | error
let restartAttempts = 0;
const MAX_RESTART_ATTEMPTS = 5;
const BACKEND_PORT = 8000;
const BACKEND_HOST = '127.0.0.1';

// ---------------------------------------------------------------------------
// Python backend management
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Port check utilities
// ---------------------------------------------------------------------------

function isPortInUse(port, host) {
  return new Promise((resolve) => {
    const socket = new (require('net').Socket)();
    socket.setTimeout(1000);

    socket.on('connect', () => {
      socket.destroy();
      resolve(true); // Port is in use — something responded
    });

    socket.on('timeout', () => {
      socket.destroy();
      resolve(false); // Port is not responding
    });

    socket.on('error', () => {
      socket.destroy();
      resolve(false); // Connection refused — port is free
    });

    socket.connect(port, host);
  });
}

function isBackendHealthy() {
  return new Promise((resolve) => {
    const req = http.get(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          // Accept both 'ok' and 'degraded' as healthy — degraded means the
          // engine is still warming up but the server is responding to requests.
          resolve(data.status === 'ok' || data.status === 'degraded' || res.statusCode === 200);
        } catch (_) {
          resolve(res.statusCode === 200);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(3000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function startPythonBackend() {
  if (pythonProcess) {
    return;
  }

  // In dev mode with npm start, backend is started by concurrently — don't spawn another
  if (process.env.ELECTRON_DEV_MODE === 'true') {
    console.log('[LocalMind] ELECTRON_DEV_MODE=true — skipping backend spawn (managed by npm)');
    backendStatus = 'starting';
    sendBackendStatus('starting');
    // Poll until the external backend is ready
    pollBackendHealth();
    return;
  }

  // Check if backend is already running and healthy before spawning
  const portInUse = await isPortInUse(BACKEND_PORT, BACKEND_HOST);
  if (portInUse) {
    const healthy = await isBackendHealthy();
    if (healthy) {
      console.log(`[LocalMind] Backend already running on port ${BACKEND_PORT} — reusing existing instance`);
      backendStatus = 'ready';
      sendBackendStatus('ready');
      restartAttempts = 0;
      // Show the window since backend is already ready
      if (mainWindow && !mainWindow.isVisible()) {
        mainWindow.show();
      }
      return;
    } else {
      console.log(`[LocalMind] Port ${BACKEND_PORT} is in use but backend is not healthy`);
    }
  }

  if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
    console.error(`[LocalMind] Backend failed to start after ${MAX_RESTART_ATTEMPTS} attempts — giving up. Kill any process on port ${BACKEND_PORT} and restart.`);
    backendStatus = 'error';
    sendBackendStatus('error');
    return;
  }

  restartAttempts++;
  console.log(`[LocalMind] Starting Python backend... (attempt ${restartAttempts}/${MAX_RESTART_ATTEMPTS})`);
  backendStatus = 'starting';
  sendBackendStatus('starting');

  // Platform-correct Python venv path: Windows uses .venv\Scripts\, Unix uses .venv/bin/
  const pythonBin = process.platform === 'win32'
    ? '.venv\\Scripts\\python.exe'
    : '.venv/bin/python';
  pythonProcess = spawn(pythonBin, [serverScript], {
    cwd: path.join(projectRoot, 'backend'),
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  pythonProcess.stdout.on('data', (data) => {
    const output = data.toString().trim();
    if (output) {
      console.log('[Python stdout]', output);
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    const output = data.toString().trim();
    if (output) {
      console.log('[Python stderr]', output);
    }

    // Detect port binding errors and stop the restart loop
    if (
      output.includes('10048') ||
      output.includes('Address already in use') ||
      output.includes('error while attempting to bind') ||
      output.includes('EADDRINUSE')
    ) {
      console.error('[LocalMind] Port is already in use — stopping restart loop. Kill any process on port ' + BACKEND_PORT + ' and restart.');
      // Remove the 'close' listener so scheduleBackendRestart doesn't fire
      pythonProcess.removeAllListeners('close');
      pythonProcess.kill();
      pythonProcess = null;
      backendStatus = 'error';
      sendBackendStatus('error');
      restartAttempts = MAX_RESTART_ATTEMPTS; // Prevent further restarts
    }
  });

  pythonProcess.on('error', (err) => {
    console.error('[LocalMind] Failed to start Python process:', err.message);
    pythonProcess = null;
    backendStatus = 'error';
    sendBackendStatus('error');
    scheduleBackendRestart();
  });

  pythonProcess.on('close', (code, signal) => {
    console.log(`[LocalMind] Python process exited with code ${code}, signal ${signal}`);
    pythonProcess = null;
    if (!isQuitting) {
      // Exit code 42 = port already in use (our convention from server.py)
      if (code === 42) {
        console.error('[LocalMind] Backend exited with port-in-use code (42) — not restarting');
        backendStatus = 'error';
        sendBackendStatus('error');
        restartAttempts = MAX_RESTART_ATTEMPTS; // Prevent further restarts
        return;
      }
      backendStatus = 'error';
      sendBackendStatus('error');
      scheduleBackendRestart();
    } else {
      backendStatus = 'stopped';
      sendBackendStatus('stopped');
    }
  });

  // Poll the health endpoint until the backend is ready
  pollBackendHealth();
}

function stopPythonBackend() {
  if (backendRestartTimer) {
    clearTimeout(backendRestartTimer);
    backendRestartTimer = null;
  }

  if (!pythonProcess) {
    return;
  }

  console.log('[LocalMind] Stopping Python backend gracefully...');

  try {
    if (process.platform === 'win32') {
      // FIX: On Windows, send Ctrl+C event first for graceful shutdown,
      // then force-kill after a 5s grace period.
      // Previously we used taskkill /T /F immediately, which gave the Python
      // process no chance to run uvicorn's shutdown handler.
      const pid = pythonProcess.pid;

      // Send SIGINT via Ctrl+C event (Windows-specific)
      // This triggers the signal handler in server.py which sets should_exit
      try {
        process.kill(pid, 'SIGINT');
      } catch (_) {
        // Process may have already exited
      }

      // Force-kill after 5 seconds if still running
      setTimeout(() => {
        try {
          process.kill(pid, 0); // check if alive
          console.log('[LocalMind] Python process still alive after 5s — force killing');
          spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {
            stdio: 'ignore',
          });
        } catch (_) {
          // already dead, good
        }
      }, 5000);
    } else {
      // Send SIGTERM; give it a moment, then SIGKILL if needed.
      pythonProcess.kill('SIGTERM');
      const pid = pythonProcess.pid;
      setTimeout(() => {
        try {
          process.kill(pid, 0); // check if still alive
          process.kill(pid, 'SIGKILL');
        } catch (_) {
          // already dead, good
        }
      }, 5000);  // Increased from 3s to 5s for graceful shutdown
    }
  } catch (err) {
    console.error('[LocalMind] Error stopping Python process:', err.message);
  }

  pythonProcess = null;
  backendStatus = 'stopped';
  sendBackendStatus('stopped');
}

function restartPythonBackend() {
  console.log('[LocalMind] Restarting Python backend...');
  restartAttempts = 0; // Reset on explicit user restart
  stopPythonBackend();
  // Give the OS a moment to free the port, then start again.
  setTimeout(() => {
    startPythonBackend();
  }, 1500);
}

function scheduleBackendRestart() {
  if (isQuitting) return;
  if (restartAttempts >= MAX_RESTART_ATTEMPTS) {
    console.error(`[LocalMind] Max restart attempts (${MAX_RESTART_ATTEMPTS}) reached — giving up`);
    return;
  }
  if (backendRestartTimer) return; // already scheduled

  console.log(`[LocalMind] Scheduling backend restart in 5 seconds... (${restartAttempts}/${MAX_RESTART_ATTEMPTS})`);
  backendRestartTimer = setTimeout(() => {
    backendRestartTimer = null;
    if (!isQuitting) {
      startPythonBackend();
    }
  }, 5000);
}

// ---------------------------------------------------------------------------
// Health polling
// ---------------------------------------------------------------------------

function pollBackendHealth() {
  const maxAttempts = 60; // 60 * 2s = 2 minutes max wait
  let attempts = 0;

  function check() {
    // Don't exit early when in dev mode (pythonProcess is null by design)
    const isDevMode = process.env.ELECTRON_DEV_MODE === 'true';
    if (!isDevMode && !pythonProcess) return;
    if (isQuitting) return;

    attempts++;
    if (attempts > maxAttempts) {
      console.warn('[LocalMind] Backend health check timed out after 2 minutes');
      backendStatus = 'error';
      sendBackendStatus('error');
      return;
    }

    const req = http.get(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          const data = JSON.parse(body);
          // Accept both 'ok' and 'degraded' as healthy
          if (data.status === 'ok' || data.status === 'degraded' || res.statusCode === 200) {
            console.log(`[LocalMind] Backend is ready (status: ${data.status})`);
            backendStatus = 'ready';
            sendBackendStatus('ready');
            restartAttempts = 0; // Reset on successful health check

            // Show the window once the backend is ready
            if (mainWindow && !mainWindow.isVisible()) {
              mainWindow.show();
            }
            return;
          }
        } catch (_) {
          // Not JSON or unexpected format -- keep polling
        }
        setTimeout(check, 2000);
      });
    });

    req.on('error', () => {
      setTimeout(check, 2000);
    });

    req.setTimeout(3000, () => {
      req.destroy();
      setTimeout(check, 2000);
    });
  }

  // Give the backend a moment to start before the first check
  setTimeout(check, 1500);
}

// ---------------------------------------------------------------------------
// Send backend status to renderer
// ---------------------------------------------------------------------------

function sendBackendStatus(status) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-status', status);
  }
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------

function createTray() {
  const { createTrayIcon } = require('./tray-icon');
  const icon = createTrayIcon();
  tray = new Tray(icon);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Window',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Restart Backend',
      click: () => {
        restartPythonBackend();
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setToolTip('LocalMind');
  tray.setContextMenu(contextMenu);

  // Double-click tray icon to show window
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ---------------------------------------------------------------------------
// Main window
// ---------------------------------------------------------------------------

function createMainWindow() {
  // Deliberate LocalMind chrome.
  // - macOS: 'hiddenInset' keeps the native traffic lights but removes the
  //   title text; the TitleBar component renders in the inset space. The
  //   system provides the window controls, so the custom buttons are hidden.
  // - Windows: fully frameless (`frame: false`) — the TitleBar component's
  //   custom min/max/close buttons (wired through the window-* IPC handlers)
  //   are the ONLY window controls.
  // - Linux: keep the default frame for now — native controls remain, and
  //   the custom buttons stay hidden (same rule as macOS).
  const isMac = process.platform === 'darwin';
  const isWindows = process.platform === 'win32';
  const windowChrome = isMac
    ? { titleBarStyle: 'hiddenInset' }
    : isWindows
      ? { frame: false }
      : {};
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'LocalMind',
    backgroundColor: '#1a1a2e',
    show: false, // shown after backend is ready
    ...windowChrome,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // Load the UI
  if (isDev) {
    mainWindow.loadURL(devServerUrl).catch(err => {
      console.error('[LocalMind] Failed to load dev server URL:', err.message);
    });
    // Open DevTools in development
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    mainWindow.loadFile(prodIndexPath).catch(err => {
      console.error('[LocalMind] Failed to load production index:', err.message);
    });
  }

  // Log page load events for debugging
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[LocalMind] UI loaded successfully');
    // If backend is already ready, show the window immediately
    if (backendStatus === 'ready' && !mainWindow.isVisible()) {
      mainWindow.show();
    }
  });

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDesc) => {
    console.error(`[LocalMind] UI failed to load: ${errorCode} — ${errorDesc}`);
  });

  // Minimize to tray on close instead of quitting
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Keep the renderer's TitleBar maximize/restore icon in sync with the
  // real window state (frameless Windows has no native indicator).
  const sendMaximizeState = () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('window-maximized-changed', mainWindow.isMaximized());
    }
  };
  mainWindow.on('maximize', sendMaximizeState);
  mainWindow.on('unmaximize', sendMaximizeState);
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function registerIpcHandlers() {
  // Select a file via native dialog
  ipcMain.handle('select-file', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Select a file',
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
  });

  // Select a folder via native dialog
  ipcMain.handle('select-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Select a folder',
      properties: ['openDirectory'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0];
  });

  // Open a file/folder with the OS default application
  ipcMain.handle('open-path', async (_event, filePath) => {
    if (!filePath || typeof filePath !== 'string') {
      return { success: false, error: 'No path provided' };
    }
    try {
      await shell.openPath(filePath);
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  });

  // Get the actual file system path for a File object
  // In Electron, webUtils.getPathForFile gives the real filesystem path
  ipcMain.handle('get-file-path', async (_event, file) => {
    try {
      // Electron 20+ exposes webUtils.getPathForFile
      const { webUtils } = require('electron');
      if (webUtils && webUtils.getPathForFile) {
        return webUtils.getPathForFile(file);
      }
      return null;
    } catch (err) {
      console.error('[LocalMind] get-file-path error:', err.message);
      return null;
    }
  });

  // Restart the Python backend
  ipcMain.handle('restart-backend', async () => {
    restartPythonBackend();
    return { success: true };
  });

  // Get the app version from package.json
  ipcMain.handle('get-app-version', async () => {
    try {
      const pkgPath = path.join(__dirname, 'package.json');
      const pkgData = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
      return pkgData.version || '0.0.0';
    } catch (_) {
      return '0.0.0';
    }
  });

  // Open an external URL in the system's default browser.
  // SECURITY: Only http/https URLs are allowed — this prevents file://,
  // javascript:, and other dangerous schemes from being opened.
  ipcMain.handle('open-external', async (_event, url) => {
    if (typeof url !== 'string') {
      return { success: false, error: 'URL must be a string' };
    }
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return { success: false, error: `Refused to open URL with scheme: ${parsed.protocol}` };
      }
      await shell.openExternal(url);
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  });

  // Window controls
  ipcMain.handle('window-minimize', () => {
    if (mainWindow) mainWindow.minimize();
  });

  ipcMain.handle('window-maximize', () => {
    if (mainWindow) {
      if (mainWindow.isMaximized()) mainWindow.unmaximize();
      else mainWindow.maximize();
    }
  });

  // Current maximize state, for the TitleBar to render the right icon on mount.
  ipcMain.handle('window-is-maximized', () => {
    return mainWindow ? mainWindow.isMaximized() : false;
  });

  ipcMain.handle('window-close', () => {
    isQuitting = true;
    app.quit();
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  createMainWindow();
  createTray();
  registerIpcHandlers();
  startPythonBackend();
});

// macOS: re-create window when dock icon clicked and no windows exist
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  } else if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
  }
});

// Prevent default -- we manage quitting ourselves (minimize to tray)
app.on('window-all-closed', () => {
  // Do nothing; the app stays in the tray
});

// Clean up before quitting
app.on('before-quit', () => {
  isQuitting = true;
  stopPythonBackend();
});

// Handle single-instance lock so only one LocalMind runs at a time.
// IMPORTANT: app.quit() cannot be called before app.whenReady(). If we
// don't get the lock, we set a flag and quit after ready.
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  console.log('[LocalMind] Another instance is already running — exiting');
  app.whenReady().then(() => app.quit());
} else {
  app.on('second-instance', () => {
    console.log('[LocalMind] Second instance detected — focusing existing window');
    if (mainWindow) {
      if (!mainWindow.isVisible()) mainWindow.show();
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

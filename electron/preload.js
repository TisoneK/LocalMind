/**
 * LocalMind Electron Preload Script
 *
 * Exposes safe IPC methods to the renderer process via contextBridge.
 * All communication between the renderer and main process goes through
 * these explicitly defined channels.
 */

const { contextBridge, ipcRenderer } = require('electron');

const electronAPI = {
  /**
   * Open a native file dialog and return the selected file path.
   * Returns null if the user cancels.
   * @returns {Promise<string|null>}
   */
  selectFile: () => ipcRenderer.invoke('select-file'),

  /**
   * Open a native folder dialog and return the selected folder path.
   * Returns null if the user cancels.
   * @returns {Promise<string|null>}
   */
  selectFolder: () => ipcRenderer.invoke('select-folder'),

  /**
   * Open a file or folder with the OS default application.
   * @param {string} filePath - Absolute path to open
   * @returns {Promise<{success: boolean, error?: string}>}
   */
  openPath: (filePath) => ipcRenderer.invoke('open-path', filePath),

  /**
   * Get the actual filesystem path for a File object.
   * This is only possible in Electron; browsers cannot access real paths.
   * @param {File} file - A File object from a drag-and-drop or file input
   * @returns {Promise<string|null>}
   */
  getFilePath: (file) => ipcRenderer.invoke('get-file-path', file),

  /**
   * Restart the Python backend process.
   * @returns {Promise<{success: boolean}>}
   */
  restartBackend: () => ipcRenderer.invoke('restart-backend'),

  /**
   * Get the application version from package.json.
   * @returns {Promise<string>}
   */
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  /**
   * Open an external URL in the system's default browser.
   * Only http/https URLs are allowed — other schemes are rejected.
   * @param {string} url - The URL to open
   * @returns {Promise<{success: boolean, error?: string}>}
   */
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  /**
   * Listen for backend status updates.
   * Status values: 'stopped' | 'starting' | 'ready' | 'error'
   * @param {function(string): void} callback - Called with the new status
   * @returns {function} Cleanup function to remove the listener
   */
  onBackendStatus: (callback) => {
    const handler = (_event, status) => {
      callback(status);
    };
    ipcRenderer.on('backend-status', handler);
    // Return a cleanup function
    return () => {
      ipcRenderer.removeListener('backend-status', handler);
    };
  },

  // Window controls
  minimizeWindow: () => ipcRenderer.invoke('window-minimize'),
  maximizeWindow: () => ipcRenderer.invoke('window-maximize'),
  closeWindow:    () => ipcRenderer.invoke('window-close'),
};

// Expose the API to the renderer via window.electronAPI
contextBridge.exposeInMainWorld('electronAPI', electronAPI);

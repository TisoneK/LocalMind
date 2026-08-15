/**
 * Electron API type declarations.
 *
 * These types describe the bridge exposed by electron/preload.js via
 * contextBridge.exposeInMainWorld('electronAPI', ...).
 *
 * In browser mode (no Electron), window.electronAPI is undefined and the
 * app falls back to web APIs (window.open, file input, etc.).
 */

interface ElectronAPI {
  selectFile: () => Promise<string | null>;
  selectFolder: () => Promise<string | null>;
  openPath: (filePath: string) => Promise<{ success: boolean; error?: string }>;
  getFilePath: (file: File) => Promise<string | null>;
  restartBackend: () => Promise<{ success: boolean }>;
  getAppVersion: () => Promise<string>;
  openExternal: (url: string) => Promise<{ success: boolean; error?: string }>;
  onBackendStatus: (callback: (status: string) => void) => () => void;
  minimizeWindow: () => Promise<void>;
  maximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  /** Host platform: 'darwin' | 'win32' | 'linux' | ... */
  platform: string;
  isMaximized: () => Promise<boolean>;
  onMaximizeChange: (callback: (maximized: boolean) => void) => () => void;
}

interface Window {
  electronAPI?: ElectronAPI;
  /** Optional API base URL override, set by Electron preload in desktop mode */
  __LOCALMIND_API__?: string;
}

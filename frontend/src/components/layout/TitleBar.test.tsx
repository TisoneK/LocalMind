import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TitleBar } from './TitleBar';

describe('TitleBar (ADR-34 B-11 / Session 234)', () => {
  beforeEach(() => {
    // Reset the electronAPI mock between tests
    (window as unknown as { electronAPI?: unknown }).electronAPI = undefined;
  });

  const win32API = (overrides: Record<string, unknown> = {}) => {
    return {
      minimizeWindow: vi.fn(),
      maximizeWindow: vi.fn(),
      closeWindow: vi.fn(),
      platform: 'win32',
      isMaximized: vi.fn().mockResolvedValue(false),
      onMaximizeChange: vi.fn(() => () => {}),
      ...overrides,
    };
  };

  it('renders the LocalMind wordmark and version pill', () => {
    render(<TitleBar version="v0.5.16" />);
    expect(screen.getByText('LocalMind')).toBeDefined();
    expect(screen.getByText('v0.5.16')).toBeDefined();
  });

  it('hides window-control buttons in browser mode (no electronAPI)', () => {
    render(<TitleBar version="v0.5.16" />);
    // The min/max/close buttons should NOT be rendered
    expect(screen.queryByTitle('Minimize')).toBeNull();
    expect(screen.queryByTitle('Maximize')).toBeNull();
    expect(screen.queryByTitle('Close')).toBeNull();
  });

  it('hides window-control buttons on macOS and reserves the traffic-light inset', () => {
    (window as unknown as { electronAPI?: unknown }).electronAPI = win32API({ platform: 'darwin' });
    render(<TitleBar version="v0.5.16" />);
    expect(screen.queryByTitle('Minimize')).toBeNull();
    expect(screen.queryByTitle('Maximize')).toBeNull();
    expect(screen.queryByTitle('Close')).toBeNull();
    const titleBar = screen.getByTestId('title-bar');
    expect(titleBar).toHaveAttribute('data-platform', 'darwin');
    expect(titleBar.className).toContain('pl-[84px]');
  });

  it('renders window-control buttons on frameless Windows', () => {
    (window as unknown as { electronAPI?: unknown }).electronAPI = win32API();
    render(<TitleBar version="v0.5.16" />);
    expect(screen.getByTitle('Minimize')).toBeDefined();
    expect(screen.getByTitle('Maximize')).toBeDefined();
    expect(screen.getByTitle('Close')).toBeDefined();
  });

  it('calls electronAPI.minimizeWindow when the minimize button is clicked', async () => {
    const mockElectronAPI = win32API();
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    const { fireEvent } = await import('@testing-library/react');
    render(<TitleBar version="v0.5.16" />);
    fireEvent.click(screen.getByTitle('Minimize'));
    expect(mockElectronAPI.minimizeWindow).toHaveBeenCalledTimes(1);
  });

  it('calls electronAPI.maximizeWindow when the maximize button is clicked', async () => {
    const mockElectronAPI = win32API();
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    const { fireEvent } = await import('@testing-library/react');
    render(<TitleBar version="v0.5.16" />);
    fireEvent.click(screen.getByTitle('Maximize'));
    expect(mockElectronAPI.maximizeWindow).toHaveBeenCalledTimes(1);
  });

  it('shows a restore icon when the window is maximized', async () => {
    const mockElectronAPI = win32API({ isMaximized: vi.fn().mockResolvedValue(true) });
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    render(<TitleBar version="v0.5.16" />);
    expect(await screen.findByTitle('Restore')).toBeDefined();
    expect(screen.queryByTitle('Maximize')).toBeNull();
  });

  it('tracks maximize state changes via onMaximizeChange', async () => {
    let notify: ((maximized: boolean) => void) | undefined;
    const mockElectronAPI = win32API({
      onMaximizeChange: vi.fn((cb: (maximized: boolean) => void) => {
        notify = cb;
        return () => {};
      }),
    });
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    const { act } = await import('@testing-library/react');
    render(<TitleBar version="v0.5.16" />);
    // Await the async isMaximized() resolution (flushed inside act by findBy*)
    expect(await screen.findByTitle('Maximize')).toBeDefined();

    act(() => notify?.(true));
    expect(screen.getByTitle('Restore')).toBeDefined();

    act(() => notify?.(false));
    expect(screen.getByTitle('Maximize')).toBeDefined();
  });

  it('renders without a version prop', () => {
    render(<TitleBar />);
    expect(screen.getByText('LocalMind')).toBeDefined();
    // No version pill rendered
    expect(screen.queryByText('v0.5.16')).toBeNull();
  });
});

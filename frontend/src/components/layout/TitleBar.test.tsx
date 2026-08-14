import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TitleBar } from './TitleBar';

describe('TitleBar (ADR-34 B-11)', () => {
  beforeEach(() => {
    // Reset the electronAPI mock between tests
    (window as unknown as { electronAPI?: unknown }).electronAPI = undefined;
  });

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

  it('renders window-control buttons when electronAPI is available', () => {
    const mockElectronAPI = {
      minimizeWindow: vi.fn(),
      maximizeWindow: vi.fn(),
      closeWindow: vi.fn(),
    };
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    render(<TitleBar version="v0.5.16" />);
    expect(screen.getByTitle('Minimize')).toBeDefined();
    expect(screen.getByTitle('Maximize')).toBeDefined();
    expect(screen.getByTitle('Close')).toBeDefined();
  });

  it('calls electronAPI.minimizeWindow when the minimize button is clicked', async () => {
    const mockElectronAPI = {
      minimizeWindow: vi.fn(),
      maximizeWindow: vi.fn(),
      closeWindow: vi.fn(),
    };
    (window as unknown as { electronAPI?: unknown }).electronAPI = mockElectronAPI;

    const { fireEvent } = await import('@testing-library/react');
    render(<TitleBar version="v0.5.16" />);
    fireEvent.click(screen.getByTitle('Minimize'));
    expect(mockElectronAPI.minimizeWindow).toHaveBeenCalledTimes(1);
  });

  it('renders without a version prop', () => {
    render(<TitleBar />);
    expect(screen.getByText('LocalMind')).toBeDefined();
    // No version pill rendered
    expect(screen.queryByText('v0.5.16')).toBeNull();
  });
});

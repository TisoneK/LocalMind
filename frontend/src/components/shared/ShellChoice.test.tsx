import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ShellChoice } from './ShellChoice';
import { localmindClient } from '@/lib/localmind/client';

afterEach(() => vi.restoreAllMocks());

const windows = {
  shell: 'auto',
  options: [
    { id: 'powershell', label: 'PowerShell', path: 'C:\\pwsh.exe', available: true },
    { id: 'cmd', label: 'Command Prompt (cmd)', path: 'C:\\cmd.exe', available: true },
    { id: 'git-bash', label: 'Git Bash', path: '', available: false },
  ],
};

describe('ShellChoice', () => {
  it('lists the shells found here, marks a missing one, and saves a pick', async () => {
    vi.spyOn(localmindClient, 'getShell').mockResolvedValue(windows);
    const save = vi.spyOn(localmindClient, 'setShell').mockResolvedValue({ shell: 'powershell', message: 'ok' });
    render(<ShellChoice />);
    const ps = await screen.findByRole('radio', { name: /PowerShell/ });
    expect(screen.getByRole('radio', { name: /Automatic/ })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: /Git Bash/ })).toBeDisabled();
    expect(screen.getByText('not installed')).toBeInTheDocument();
    fireEvent.click(ps);
    await waitFor(() => expect(save).toHaveBeenCalledWith('powershell'));
    expect(ps).toHaveAttribute('aria-checked', 'true');
  });

  it('puts the choice back and says why when the backend refuses', async () => {
    vi.spyOn(localmindClient, 'getShell').mockResolvedValue(windows);
    vi.spyOn(localmindClient, 'setShell').mockRejectedValue(new Error('PowerShell is not installed'));
    render(<ShellChoice />);
    fireEvent.click(await screen.findByRole('radio', { name: /PowerShell/ }));
    expect(await screen.findByText(/not installed on|is not installed/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Automatic/ })).toHaveAttribute('aria-checked', 'true');
  });
});

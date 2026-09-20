import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PackageEnvChoice } from './PackageEnvChoice';
import { localmindClient } from '@/lib/localmind/client';

afterEach(() => vi.restoreAllMocks());

describe('PackageEnvChoice', () => {
  it('shows the saved choice and saves a change', async () => {
    vi.spyOn(localmindClient, 'getPackageEnv').mockResolvedValue({ package_env: 'localmind', packages_dir: '/h/packages' });
    const save = vi.spyOn(localmindClient, 'setPackageEnv').mockResolvedValue({ package_env: 'system', packages_dir: '/h/packages' });
    render(<PackageEnvChoice />);
    const local = screen.getByRole('radio', { name: 'LocalMind' });
    await waitFor(() => expect(local).toHaveAttribute('aria-checked', 'true'));
    fireEvent.click(screen.getByRole('radio', { name: 'System' }));
    expect(screen.getByRole('radio', { name: 'System' })).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => expect(save).toHaveBeenCalledWith('system'));
  });

  it('puts the choice back and says so when saving fails', async () => {
    vi.spyOn(localmindClient, 'getPackageEnv').mockResolvedValue({ package_env: 'localmind', packages_dir: '/h/packages' });
    vi.spyOn(localmindClient, 'setPackageEnv').mockRejectedValue(new Error('nope'));
    render(<PackageEnvChoice />);
    await waitFor(() => expect(screen.getByRole('radio', { name: 'LocalMind' })).toHaveAttribute('aria-checked', 'true'));
    fireEvent.click(screen.getByRole('radio', { name: 'System' }));
    expect(await screen.findByText(/couldn't save/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'LocalMind' })).toHaveAttribute('aria-checked', 'true');
  });
});

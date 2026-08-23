'use client';

import React, { useState } from 'react';
import { Package, Loader2 } from 'lucide-react';

interface PackageInstallerProps {
  onExecute: (command: string) => Promise<unknown>;
  isRunning?: boolean;
}

const MANAGERS = [
  { id: 'pip', label: 'pip install', placeholder: 'package-name', command: (pkg: string) => `pip install ${pkg}` },
  { id: 'npm', label: 'npm install', placeholder: 'package-name', command: (pkg: string) => `npm install ${pkg}` },
  { id: 'ollama', label: 'Ollama pull', placeholder: 'model-name', command: (pkg: string) => `ollama pull ${pkg}` },
];

export function PackageInstaller({ onExecute, isRunning }: PackageInstallerProps) {
  const [managerIdx, setManagerIdx] = useState(0);
  const [packageInput, setPackageInput] = useState('');
  const manager = MANAGERS[managerIdx];

  const handleInstall = async () => {
    if (!packageInput.trim() || isRunning) return;
    const cmd = manager.command(packageInput.trim());
    setPackageInput('');
    await onExecute(cmd);
  };

  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-brand-border bg-brand-bg-dark" data-testid="package-installer">
      <Package className="h-3 w-3 text-brand-amber shrink-0" />
      <select
        value={managerIdx}
        onChange={(e) => setManagerIdx(Number(e.target.value))}
        className="bg-brand-bg-panel border border-brand-border rounded px-1.5 py-0.5 text-[10px] text-brand-green-soft focus:outline-none"
        disabled={isRunning}
        data-testid="package-manager-select"
      >
        {MANAGERS.map((m, i) => (
          <option key={m.id} value={i}>{m.label}</option>
        ))}
      </select>
      <input
        type="text"
        value={packageInput}
        onChange={(e) => setPackageInput(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleInstall()}
        placeholder={manager.placeholder}
        className="flex-1 bg-transparent border border-brand-border rounded px-2 py-0.5 text-[10px] text-brand-green-soft placeholder:text-brand-green-muted focus:outline-none focus:border-brand-green/40"
        disabled={isRunning}
        data-testid="package-input"
      />
      <button
        onClick={handleInstall}
        disabled={!packageInput.trim() || isRunning}
        className="px-2 py-0.5 rounded bg-brand-green/10 text-brand-green text-[10px] font-medium hover:bg-brand-green/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        data-testid="package-install-btn"
      >
        {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Install'}
      </button>
    </div>
  );
}

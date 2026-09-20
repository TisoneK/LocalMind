import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TerminalBlock } from './TerminalBlock';
import { isTerminalTool } from '@/lib/localmind/turnTimeline';
import { TurnView } from './TurnView';
import type { ToolCall } from '@/types';

const ESC = String.fromCharCode(27);

const tool = (over: Partial<ToolCall> = {}): ToolCall => ({
  id: 't1',
  name: 'shell',
  status: 'done',
  input: 'ls -la',
  output: 'total 0\nfile.txt',
  ...over,
});

describe('TerminalBlock', () => {
  it('shows the command with a prompt and its output', () => {
    render(<TerminalBlock tool={tool()} />);
    expect(screen.getByText('$')).toBeInTheDocument();
    expect(screen.getByText('ls -la')).toBeInTheDocument();
    expect(screen.getByText(/file\.txt/)).toBeInTheDocument();
  });

  it('strips terminal colour codes from the output', () => {
    render(<TerminalBlock tool={tool({ output: `${ESC}[32mok${ESC}[0m done` })} />);
    expect(screen.getByText('ok done')).toBeInTheDocument();
  });

  it('marks a failed command clearly and shows its error', () => {
    render(<TerminalBlock tool={tool({ status: 'failed', output: undefined, error: 'command not found: foo' })} />);
    expect(screen.getByText('Command failed')).toBeInTheDocument();
    expect(screen.getByText('command not found: foo')).toBeInTheDocument();
  });

  it('says so when a finished command printed nothing', () => {
    render(<TerminalBlock tool={tool({ output: '' })} />);
    expect(screen.getByText('(no output)')).toBeInTheDocument();
  });

  it('labels a code step as python instead of a shell prompt', () => {
    render(<TerminalBlock tool={tool({ name: 'code_exec', input: 'print(1)', output: '1' })} />);
    expect(screen.getByText('python')).toBeInTheDocument();
    expect(screen.queryByText('$')).toBeNull();
  });

  it('copies the command', () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<TerminalBlock tool={tool()} />);
    fireEvent.click(screen.getByLabelText('Copy command'));
    expect(writeText).toHaveBeenCalledWith('ls -la');
  });

  it('only shell and code steps count as terminal steps', () => {
    expect(isTerminalTool(tool())).toBe(true);
    expect(isTerminalTool(tool({ name: 'code_exec' }))).toBe(true);
    expect(isTerminalTool(tool({ name: 'file_write' }))).toBe(false);
    expect(isTerminalTool(undefined)).toBe(false);
  });
});

describe('TurnView terminal steps', () => {
  it('opens a shell step as a terminal inside the turn', () => {
    render(<TurnView message={{ toolCalls: [tool()] }} />);
    fireEvent.click(screen.getByText('Ran 1 tool'));
    fireEvent.click(screen.getByText('Ran command'));
    expect(screen.getByTestId('terminal-block')).toBeInTheDocument();
  });
});

describe('TerminalBlock failure text', () => {
  it('shows "(no output)" rather than the model-facing recovery advice when the command printed nothing', () => {
    render(
      <TerminalBlock
        tool={{
          id: 't', name: 'shell', input: 'ls /nope', status: 'failed',
          output: "[Tool 'shell' returned error_type='command_failed']\nCommand failed:\n---\n[RECOVERY]: `shell` command failed. Check the error message, fix the command, and retry.",
        } as never}
      />,
    );
    expect(screen.queryByText(/RECOVERY/)).toBeNull();
    expect(screen.getByText('(no output)')).toBeInTheDocument();
  });
});

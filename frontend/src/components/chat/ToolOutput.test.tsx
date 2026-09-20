import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ToolOutput } from './ToolOutput';
import { ThoughtText } from './ThoughtText';
import { TurnView } from './TurnView';
import type { ToolCall } from '@/types';

const results = (n: number) =>
  `Search results via **DuckDuckGo** (${n} results):\n\n` +
  Array.from({ length: n }, (_, i) => `${i + 1}. **Result ${i + 1}**\n   https://site${i + 1}.example.com/page\n   Snippet number ${i + 1}.`).join('\n\n');

const tool = (over: Partial<ToolCall> = {}): ToolCall => ({ id: 't', name: 'web_search', status: 'done', input: 'q', ...over });

describe('ToolOutput', () => {
  it('shows a search as result links with their host, not a text dump', () => {
    render(<ToolOutput tool={tool({ output: results(3) })} />);
    const link = screen.getByRole('link', { name: /Result 1/ });
    expect(link).toHaveAttribute('href', 'https://site1.example.com/page');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('site1.example.com')).toBeInTheDocument();
    expect(screen.getByText('3 results · DuckDuckGo')).toBeInTheDocument();
    expect(screen.queryByText(/Search results via/)).toBeNull();
  });

  it('shows the first few results and offers the rest', () => {
    render(<ToolOutput tool={tool({ output: results(8) })} />);
    expect(screen.getAllByRole('link')).toHaveLength(4);
    fireEvent.click(screen.getByText('Show all 8 results'));
    expect(screen.getAllByRole('link')).toHaveLength(8);
  });

  it('shows a fetch with its source and a collapsed body, and says what was cut', () => {
    const body = Array.from({ length: 20 }, (_, i) => ` "line${i}": ${i}`).join('\n');
    render(<ToolOutput tool={tool({ name: 'web_fetch', output: `Source: https://wttr.in/K?format=j1\n\n{\n${body}\n… [8069 chars truncated] …\n}\n\n[... content truncated]` })} />);
    expect(screen.getByRole('link', { name: /wttr\.in/ })).toBeInTheDocument();
    expect(screen.getByText('JSON')).toBeInTheDocument();
    expect(screen.getByText('· incomplete')).toBeInTheDocument(); // the backend cut it, so it will not parse
    expect(screen.queryByText(/chars truncated/)).toBeNull();
    expect(screen.getByText(/8,069 characters of the original were not kept/)).toBeInTheDocument();
    expect(screen.getByText(/Show all \d+ lines/)).toBeInTheDocument();
  });

  it('caps plain text and can expand it', () => {
    render(<ToolOutput tool={tool({ name: 'file_read', output: Array.from({ length: 30 }, (_, i) => `row ${i}`).join('\n') })} />);
    expect(screen.queryByText(/row 20/)).toBeNull();
    fireEvent.click(screen.getByText('Show all 30 lines'));
    expect(screen.getByText(/row 20/)).toBeInTheDocument();
  });
});

describe('ThoughtText', () => {
  it('is quiet and cut to a few lines with a toggle', () => {
    render(<ThoughtText text={Array.from({ length: 12 }, (_, i) => `thought ${i}`).join('\n')} />);
    expect(screen.queryByText(/thought 9/)).toBeNull();
    fireEvent.click(screen.getByText('Show all 12 lines'));
    expect(screen.getByText(/thought 9/)).toBeInTheDocument();
  });

  it('renders nothing for blank text', () => {
    const { container } = render(<ThoughtText text="   " />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('TurnView reasoning-only reply', () => {
  it('shows the reasoning itself, not a second "Thought" row under "Thought for …"', () => {
    render(<TurnView message={{ thinking: 'The user greeted me.', thinkMs: 2200 }} />);
    fireEvent.click(screen.getByText('Thought for 2.2s'));
    expect(screen.getByTestId('thought-text')).toHaveTextContent('The user greeted me.');
    expect(screen.queryByText('Thought')).toBeNull();
  });
});

describe('ToolOutput JSON', () => {
  it('re-indents valid JSON and colours keys, strings, numbers and literals', () => {
    const { container } = render(<ToolOutput tool={tool({ name: 'api', output: '{"city":"Kitengela","temp":18,"clear":true,"rain":null}' })} />);
    const pre = container.querySelector('pre') as HTMLElement;
    expect(pre.textContent).toBe('{\n  "city": "Kitengela",\n  "temp": 18,\n  "clear": true,\n  "rain": null\n}');
    expect(screen.getByText('"city"').className).toContain('text-brand-blue');
    expect(screen.getByText('"Kitengela"').className).toContain('text-brand-green');
    expect(screen.getByText('18').className).toContain('text-brand-amber');
    expect(screen.getByText('true').className).toContain('text-brand-purple');
    expect(screen.queryByText('· incomplete')).toBeNull();
  });

  it('does not colour ordinary text', () => {
    const { container } = render(<ToolOutput tool={tool({ name: 'file_read', output: 'Size: 16 bytes\nLines: 1' })} />);
    expect(container.querySelector('pre span')).toBeNull();
  });
});


describe('TurnView tool icons', () => {
  it('colours a step by the kind of work', () => {
    render(
      <TurnView
        message={{
          toolCalls: [
            { id: '1', name: 'web_search', status: 'done', input: 'q', output: 'x', iteration: 1 },
            { id: '2', name: 'file_write', status: 'done', input: '/w/a.txt:\nx', output: 'ok', iteration: 2 },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByText('Ran 2 tools'));
    expect(document.querySelector('[data-tool-kind="web"]')?.getAttribute('class')).toContain('text-brand-blue');
    expect(document.querySelector('[data-tool-kind="write"]')?.getAttribute('class')).toContain('text-brand-amber');
  });
});

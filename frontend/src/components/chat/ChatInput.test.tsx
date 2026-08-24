import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatInput } from './ChatInput';

describe('ChatInput', () => {
  it('sends the typed message on Enter', async () => {
    const onSend = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onAbort={() => {}}
        isStreaming={false}
      />,
    );

    const textarea = screen.getByPlaceholderText(/Ask LocalMind to build, debug, or explain/i);
    await userEvent.type(textarea, 'hello world{enter}');

    expect(onSend).toHaveBeenCalledTimes(1);
    // B-2026-08-24-3: the per-message tool selector was removed — send just
    // the message (the Chat/Agent/Auto mode picker replaces the intent hint).
    expect(onSend).toHaveBeenCalledWith('hello world');
    // Input is cleared after send.
    expect(screen.getByPlaceholderText(/Ask LocalMind to build, debug, or explain/i)).toHaveValue('');
  });

  it('does not send an empty or whitespace message', async () => {
    const onSend = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onAbort={() => {}}
        isStreaming={false}
      />,
    );

    const textarea = screen.getByPlaceholderText(/Ask LocalMind to build, debug, or explain/i);
    await userEvent.type(textarea, '   {enter}');
    expect(onSend).not.toHaveBeenCalled();
  });


  it('aborts instead of sending while streaming', async () => {
    const onSend = vi.fn();
    const onAbort = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onAbort={onAbort}
        isStreaming={true}
      />,
    );

    // Streaming: textarea disabled, abort button shown, send button hidden.
    expect(screen.getByPlaceholderText(/Ask LocalMind to build, debug, or explain/i)).toBeDisabled();
    expect(screen.getByTitle('Stop generating')).toBeInTheDocument();
    expect(screen.queryByTitle(/Send/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByTitle('Stop generating'));
    expect(onAbort).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('steers with an injected message while streaming', async () => {
    const onSteer = vi.fn();
    render(
      <ChatInput
        onSend={() => {}}
        onAbort={() => {}}
        onSteer={onSteer}
        isStreaming={true}
      />,
    );

    const steer = screen.getByPlaceholderText(/Steer the agent at the next step/i);
    await userEvent.type(steer, 'please focus on the tests{enter}');
    expect(onSteer).toHaveBeenCalledWith('please focus on the tests');
  });
});

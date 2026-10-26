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

    const textarea = screen.getByPlaceholderText(/Message LocalMind, or describe a task/i);
    await userEvent.type(textarea, 'hello world{enter}');

    expect(onSend).toHaveBeenCalledTimes(1);
    // The per-message tool selector was removed — send just
    // the message (the Chat/Agent/Auto mode picker replaces the intent hint).
    expect(onSend).toHaveBeenCalledWith('hello world');
    // Input is cleared after send.
    expect(screen.getByPlaceholderText(/Message LocalMind, or describe a task/i)).toHaveValue('');
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

    const textarea = screen.getByPlaceholderText(/Message LocalMind, or describe a task/i);
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

    // Streaming: the composer stays typable so it can also steer, the send
    // button is replaced by abort, and no steer action shows while empty.
    expect(screen.getByRole('textbox')).not.toBeDisabled();
    expect(screen.getByTitle('Stop generating')).toBeInTheDocument();
    expect(screen.queryByTitle('Send message')).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Steer the agent/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByTitle('Stop generating'));
    expect(onAbort).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('steers from the main composer while streaming', async () => {
    const onSteer = vi.fn();
    const onAbort = vi.fn();
    render(
      <ChatInput
        onSend={() => {}}
        onAbort={onAbort}
        onSteer={onSteer}
        isStreaming={true}
      />,
    );

    // One input field: steering happens in the same composer.
    expect(screen.getAllByRole('textbox')).toHaveLength(1);
    const box = screen.getByPlaceholderText(/Steer the agent at the next step/i);
    await userEvent.type(box, 'please focus on the tests');

    await userEvent.click(screen.getByTitle(/Steer the agent/i));

    expect(onSteer).toHaveBeenCalledWith('please focus on the tests');
    expect(onAbort).not.toHaveBeenCalled();
    expect(box).toHaveValue('');
  });

  it('steers on Enter while streaming without aborting', async () => {
    const onSteer = vi.fn();
    const onAbort = vi.fn();
    const onSend = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onAbort={onAbort}
        onSteer={onSteer}
        isStreaming={true}
      />,
    );

    const box = screen.getByRole('textbox');
    await userEvent.type(box, 'go left{enter}');

    expect(onSteer).toHaveBeenCalledWith('go left');
    expect(onAbort).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue('');
  });
});

describe('ChatInput width', () => {
  it('shares the chat column width so it lines up with the replies above it', () => {
    render(<ChatInput onSend={() => {}} onAbort={() => {}} isStreaming={false} />);
    expect(screen.getByTestId('composer-column').className).toContain('max-w-3xl');
  });
});


describe('ChatInput send hint', () => {
  it('says plain Enter sends, because that is what sends', async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} onAbort={() => {}} isStreaming={false} />);
    expect(screen.queryByText('⌘')).toBeNull();
    const box = screen.getByRole('textbox');
    await userEvent.type(box, 'hello{Enter}');
    expect(onSend).toHaveBeenCalledWith('hello');
  });
});

/**
 * Minimal SSE line parser used by the chat stream.
 *
 * The backend sends one JSON payload per `data:` line. Keeping this parser
 * independent from fetch makes stream-boundary behavior testable, including
 * responses that end without a trailing newline.
 */

export interface SSEParser {
  /** Add a decoded network chunk. Returns true after a [DONE] event. */
  push(chunk: string): boolean;
  /** Process any final unterminated line. Returns true after a [DONE] event. */
  flush(): boolean;
}

export function createSSEParser(
  onData: (data: string) => void,
  onDone: () => void,
): SSEParser {
  let buffer = '';
  let terminated = false;

  const processLine = (line: string): void => {
    // `\r` is part of a CRLF line ending, not part of the SSE payload.
    const normalizedLine = line.endsWith('\r') ? line.slice(0, -1) : line;
    if (!normalizedLine.startsWith('data: ')) return;

    const data = normalizedLine.slice(6);
    if (data === '[DONE]') {
      terminated = true;
      onDone();
      return;
    }
    onData(data);
  };

  const processBuffer = (): boolean => {
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      processLine(line);
      if (terminated) return true;
    }
    return false;
  };

  return {
    push(chunk: string): boolean {
      if (terminated) return true;
      buffer += chunk;
      return processBuffer();
    },

    flush(): boolean {
      if (terminated) return true;
      if (buffer) {
        processLine(buffer);
        buffer = '';
      }
      return terminated;
    },
  };
}

/** The interactive terminal hook (command history, completion, streamed output). */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { localmindClient } from '@/lib/localmind/client';
import type {
  TerminalLine,
  CompletionSuggestion,
} from '@/types';

// ─── useTerminal ───────────────────────────────────────────────────────

export function useTerminal(initialSessionId: string = 'default') {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [cwd, setCwd] = useState('~');
  const [history, setHistory] = useState<string[]>([]);

  // Load session info on mount or session change
  useEffect(() => {
    let mounted = true;
    const loadSession = async () => {
      try {
        const info = await localmindClient.getTerminalSessionInfo(sessionId);
        if (mounted) {
          setCwd(info.cwd.replace(/^\/home\/[^/]+/, '~').replace(/^\/Users\/[^/]+/, '~'));
        }
      } catch {
        // Keep defaults
      }
    };
    loadSession();
    return () => { mounted = false; };
  }, [sessionId]);

  // Load command history on session change
  useEffect(() => {
    let mounted = true;
    const loadHistory = async () => {
      try {
        const res = await localmindClient.getTerminalHistory(sessionId, 100);
        if (mounted) {
          setHistory(res.commands);
        }
      } catch {
        // Keep empty
      }
    };
    loadHistory();
    return () => { mounted = false; };
  }, [sessionId]);

  const execute = useCallback(
    async (command: string, commandCwd?: string) => {
      const now = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      const cmdLine: TerminalLine = {
        id: `cmd-${Date.now()}`,
        type: 'command',
        content: `$ ${command}`,
        timestamp: now,
      };
      setLines((prev) => [...prev, cmdLine]);
      setIsRunning(true);

      try {
        const result = await localmindClient.executeTerminal(
          command,
          commandCwd,
          sessionId
        );

        const outputTime = new Date().toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });

        // Update cwd from response
        if (result.cwd) {
          setCwd(result.cwd.replace(/^\/home\/[^/]+/, '~').replace(/^\/Users\/[^/]+/, '~'));
        }

        // Add stdout lines
        if (result.stdout) {
          for (const line of result.stdout.split('\n')) {
            setLines((prev) => [
              ...prev,
              {
                id: `out-${Date.now()}-${Math.random()}`,
                type: 'output',
                content: line,
                timestamp: outputTime,
              },
            ]);
          }
        }

        // Add stderr lines
        if (result.stderr) {
          for (const line of result.stderr.split('\n')) {
            setLines((prev) => [
              ...prev,
              {
                id: `err-${Date.now()}-${Math.random()}`,
                type: 'error',
                content: line,
                timestamp: outputTime,
              },
            ]);
          }
        }

        // Add exit code info for non-zero exits
        if (result.exitCode !== 0) {
          setLines((prev) => [
            ...prev,
            {
              id: `info-${Date.now()}`,
              type: 'info',
              content: `Exit code: ${result.exitCode} (${Math.round(result.duration * 1000)}ms)`,
              timestamp: outputTime,
              exitCode: result.exitCode,
              duration: result.duration,
            },
          ]);
        } else if (result.stdout || result.stderr) {
          // Add success indicator for zero-exit with output
          setLines((prev) => [
            ...prev,
            {
              id: `success-${Date.now()}`,
              type: 'success',
              content: `Completed in ${Math.round(result.duration * 1000)}ms`,
              timestamp: outputTime,
              duration: result.duration,
            },
          ]);
        }

        // Update local history
        setHistory((prev) => [...prev, command]);

        return result;
      } catch (err) {
        setLines((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            type: 'error',
            content: err instanceof Error ? err.message : 'Command execution failed',
            timestamp: now,
          },
        ]);
        throw err;
      } finally {
        setIsRunning(false);
      }
    },
    [sessionId]
  );

  const clear = useCallback(() => {
    setLines([]);
  }, []);

  const changeSession = useCallback((newSessionId: string) => {
    setSessionId(newSessionId);
    setLines([]);
  }, []);

  const tabComplete = useCallback(
    async (partial: string): Promise<CompletionSuggestion[]> => {
      try {
        return await localmindClient.getTerminalCompletions(partial, sessionId);
      } catch {
        return [];
      }
    },
    [sessionId]
  );

  const addToolOutput = useCallback(
    (event: { tool: string; command: string; output: string; success: boolean; latencyMs: number; label?: string; toolArgs?: string }) => {
      const now = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      // Determine the tool badge and prefix based on tool type
      const toolBadgeMap: Record<string, { badge: string; prefix: string }> = {
        shell: { badge: 'shell', prefix: '$' },
        code_exec: { badge: 'code', prefix: '>>>' },
        file_task: { badge: 'file', prefix: 'read' },
        file_write: { badge: 'edit', prefix: 'write' },
        edit_file: { badge: 'edit', prefix: 'edit' },
        web_search: { badge: 'search', prefix: 'search' },
        memory_op: { badge: 'memory', prefix: 'mem' },
        sysinfo: { badge: 'system', prefix: 'sys' },
      };
      const toolInfo = toolBadgeMap[event.tool] || { badge: 'tool', prefix: '>' };

      // Add the command/action line with agent marker and tool badge
      const commandDisplay = event.command.length > 100
        ? event.command.substring(0, 100) + '...'
        : event.command;

      setLines((prev) => [
        ...prev,
        {
          id: `sys-${Date.now()}`,
          type: 'system' as const,
          content: `${toolInfo.prefix} ${commandDisplay}`,
          timestamp: now,
          source: 'agent' as const,
          toolName: toolInfo.badge,
          toolLabel: event.label || '',
        },
      ]);

      // Add the output lines
      if (event.output) {
        // For non-shell tools, trim very long output
        const maxOutputLines = ['shell', 'code_exec'].includes(event.tool) ? 100 : 30;
        const outputLines = event.output.split('\n').slice(0, maxOutputLines);
        for (const line of outputLines) {
          setLines((prev) => [
            ...prev,
            {
              id: `tool-out-${Date.now()}-${Math.random()}`,
              type: event.success ? ('output' as const) : ('error' as const),
              content: line,
              timestamp: now,
              source: 'agent' as const,
              toolName: toolInfo.badge,
            },
          ]);
        }
        // Indicate truncated output
        const totalLines = event.output.split('\n').length;
        if (totalLines > maxOutputLines) {
          setLines((prev) => [
            ...prev,
            {
              id: `trunc-${Date.now()}`,
              type: 'info' as const,
              content: `... ${totalLines - maxOutputLines} more lines truncated`,
              timestamp: now,
              source: 'agent' as const,
            },
          ]);
        }
      }

      // Add completion status
      setLines((prev) => [
        ...prev,
        {
          id: `tool-status-${Date.now()}`,
          type: event.success ? ('success' as const) : ('error' as const),
          content: event.success
            ? `Completed in ${event.latencyMs}ms`
            : `Failed (${event.latencyMs}ms)`,
          timestamp: now,
          duration: event.latencyMs,
          source: 'agent' as const,
          toolName: toolInfo.badge,
        },
      ]);
    },
    []
  );

  return {
    lines,
    isRunning,
    execute,
    clear,
    sessionId,
    cwd,
    history,
    changeSession,
    tabComplete,
    addToolOutput,
  };
}


'use client';

import { useState, useRef, useEffect, type ReactNode } from 'react';
import {
  Send,
  ChevronDown,
  Zap,
  Square,
  Navigation,
  MessageSquare,
  Bot,
  Pencil,
  X,
} from 'lucide-react';
import { InputContextMenu } from './InputContextMenu';

// Chat mode options.
const chatModeOptions = [
  { id: 'auto' as const, label: 'Auto', icon: <Zap className="h-3 w-3" />, tooltip: 'Classifier decides (default)' },
  { id: 'agent' as const, label: 'Agent', icon: <Bot className="h-3 w-3" />, tooltip: 'Always full agent loop' },
  { id: 'direct' as const, label: 'Chat', icon: <MessageSquare className="h-3 w-3" />, tooltip: 'Lightweight chat, no tools' },
];

interface ChatInputProps {
  onSend: (message: string, tool?: string) => void;
  onAbort: () => void;
  onSteer?: (message: string) => void;
  isStreaming: boolean;
  /** Retained for the call site; no longer used since the per-message tool
   *  selector was removed. */
  sessionId?: string;
  /** Current chat mode. */
  chatMode?: string;
  /** Callback to change chat mode. */
  onChatModeChange?: (mode: 'auto' | 'agent' | 'direct') => void;
  /** Your last message, put back to rewrite. A new `key` loads it (the same text twice still reloads). */
  prefill?: { text: string; key: number } | null;
  /** Send the rewritten message in place of the last turn. */
  onEditSend?: (message: string) => void;
  /** Called when editing ends without sending. */
  onEditCancel?: () => void;
  /** Replaces the default keyboard hints under the composer (the chat's
   *  turn/step stats strip rides here). */
  footer?: ReactNode;
}

export function ChatInput({ onSend, onAbort, onSteer, isStreaming, chatMode, onChatModeChange, prefill, onEditSend, onEditCancel, footer }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [editing, setEditing] = useState(false);

  // "Edit" on your last message loads it here. The text/editing state is
  // adjusted during render (state-mirrors-a-prop pattern: fires once per new
  // prefill object, no effect-time setState cascade); focusing stays in the
  // effect below, where side effects belong.
  const [lastPrefill, setLastPrefill] = useState<ChatInputProps['prefill']>(undefined);
  if (prefill && prefill !== lastPrefill) {
    setLastPrefill(prefill);
    setInput(prefill.text);
    setEditing(true);
  }
  useEffect(() => {
    if (!prefill) return;
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      }
    });
  }, [prefill]);

  const cancelEdit = () => {
    setEditing(false);
    setInput('');
    onEditCancel?.();
  };
  const modeMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modeMenuRef.current && !modeMenuRef.current.contains(e.target as Node)) {
        setModeMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const currentModeOption = chatModeOptions.find((m) => m.id === (chatMode || 'auto')) ?? chatModeOptions[0];

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || isStreaming) return;
    // The chat-mode picker (Auto/Agent/Chat)
    // replaced the old per-message tool/intent hint — send just the message.
    if (editing && onEditSend) onEditSend(msg);
    else onSend(msg);
    setEditing(false);
    setInput('');
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleAbort = () => {
    onAbort();
  };

  // While a turn is open, the same composer steers the agent at the next
  // step boundary instead of aborting and re-running. The backend drains the
  // message at the next loop iteration.
  const handleSteer = () => {
    const msg = input.trim();
    if (!msg || !onSteer) return;
    onSteer(msg);
    setInput('');
    setEditing(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  return (
    <div className="border-t border-brand-border bg-brand-bg-base">
      {/* Input area */}
      <div className="mx-auto w-full max-w-3xl px-4 pt-3 pb-2" data-testid="composer-column">
        {editing && (
          <div className="mb-1.5 flex items-center gap-1.5 text-[10.5px] text-brand-amber" data-testid="editing-banner">
            <Pencil className="h-3 w-3" aria-hidden />
            <span className="flex-1">Editing your last message — sending replaces that turn</span>
            <button type="button" onClick={cancelEdit} className="rounded p-0.5 hover:bg-brand-amber/10" title="Cancel editing (Esc)">
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        <div className="relative flex items-end gap-2 bg-brand-bg-chat-input border border-brand-border rounded-xl px-3 py-2.5 focus-within:border-brand-green/40 transition-colors">
          {/* Steering lives on the LEFT of the composer so it never touches
              or crowds the Stop button on the right. It appears only while a
              turn is open and the input has text. */}
          {isStreaming && onSteer && input.trim() && (
            <button
              type="button"
              onClick={handleSteer}
              className="flex shrink-0 items-center gap-1 self-center rounded-md border border-brand-green/30 bg-brand-green/10 px-2 py-1 text-[10px] font-medium text-brand-green transition-colors hover:bg-brand-green/20"
              title="Steer the agent — inject at the next step (it keeps running)"
            >
              <Navigation className="h-3 w-3" />
              Steer
            </button>
          )}
          {/* Textarea — wrapped in the right-click edit menu
              (Cut / Copy / Paste / Select all) */}
          <InputContextMenu textareaRef={textareaRef} value={input} onChange={setInput}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                isStreaming
                  ? 'Steer the agent at the next step… (no abort)'
                  : chatMode === 'direct'
                    ? 'Message LocalMind — chat mode, no tools…'
                    : 'Message LocalMind, or describe a task to run…'
              }
              className="flex-1 bg-transparent text-[13px] text-brand-green-soft placeholder:text-brand-green-muted resize-none outline-none min-h-[22px] max-h-[160px] font-sans leading-relaxed"
              rows={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (isStreaming) {
                    if (onSteer) handleSteer();
                  } else {
                    handleSend();
                  }
                } else if (e.key === 'Escape' && editing) {
                  e.preventDefault();
                  cancelEdit();
                }
              }}
            />
          </InputContextMenu>

          {/* Action buttons */}
          <div className="flex items-center gap-1 shrink-0 pb-0.5">
            {/* Chat mode picker */}
            {onChatModeChange && (
              <div className="relative" ref={modeMenuRef}>
                <button
                  onClick={() => setModeMenuOpen(!modeMenuOpen)}
                  className={`flex items-center gap-1 rounded-full border border-brand-border px-2 py-0.5 text-[10px] transition-colors disabled:opacity-40 ${
                    chatMode === 'direct'
                      ? 'text-brand-amber hover:bg-brand-border'
                      : chatMode === 'agent'
                        ? 'text-brand-blue hover:bg-brand-border'
                        : 'text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-border'
                  }`}
                  disabled={isStreaming}
                  title={`Chat mode: ${currentModeOption.tooltip}`}
                >
                  {currentModeOption.icon}
                  <span>{currentModeOption.label}</span>
                  <ChevronDown className="h-2.5 w-2.5" />
                </button>
                {modeMenuOpen && (
                  <div className="absolute bottom-full right-0 mb-1 w-44 bg-brand-bg-rail border border-brand-border rounded-md shadow-xl z-50 overflow-hidden">
                    <div className="p-1">
                      {chatModeOptions.map((mode) => (
                        <button
                          key={mode.id}
                          onClick={() => {
                            onChatModeChange(mode.id);
                            setModeMenuOpen(false);
                          }}
                          className={`flex items-center gap-2 w-full px-2 py-1 rounded text-[10px] hover:bg-brand-border transition-colors ${
                            mode.id === (chatMode || 'auto')
                              ? 'text-brand-green'
                              : 'text-brand-green-soft'
                          }`}
                          title={mode.tooltip}
                        >
                          {mode.icon}
                          <span>{mode.label}</span>
                          <span className="ml-auto text-[9px] text-brand-green-muted">{mode.tooltip}</span>
                          {mode.id === (chatMode || 'auto') && (
                            <span className="text-brand-green">✓</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Send / Abort — the steering action lives on the left side of
                the composer, so this cluster is never shared with it. */}
            {isStreaming ? (
              <button
                onClick={handleAbort}
                className="rounded-full p-2 bg-brand-red text-white hover:bg-brand-red/80 transition-colors"
                title="Stop generating"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className={`rounded-full p-2 transition-colors ${
                  input.trim()
                    ? 'bg-brand-green text-white hover:bg-brand-green/80'
                    : 'bg-brand-border text-brand-green-faint'
                }`}
                title="Send message"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Footer: the chat's stats strip when provided, keyboard hints otherwise */}
      {footer ?? (
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 pb-2">
          <div className="flex items-center gap-3">
            <span className="text-[9px] text-brand-green-muted">
              <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted">Enter</kbd>
              {' '}to send
            </span>
            <span className="text-[9px] text-brand-green-muted">
              <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted mr-0.5">Shift</kbd>
              <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted">Enter</kbd>
              {' '}new line
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

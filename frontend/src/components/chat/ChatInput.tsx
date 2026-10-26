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
  const [steerInput, setSteerInput] = useState('');
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

  const handleSteer = () => {
    const msg = steerInput.trim();
    if (!msg || !onSteer) return;
    onSteer(msg);
    setSteerInput('');
  };

  return (
    <div className="border-t border-brand-border bg-brand-bg-base">
      {/* Input area */}
      <div className="mx-auto w-full max-w-3xl px-4 pt-3 pb-2" data-testid="composer-column">
        {/* Steering without aborting — while the agent
            is running, inject a message at the next step boundary instead of
            abort + re-run. The backend drains it at the next loop iteration. */}
        {isStreaming && onSteer && (
          <div className="flex items-center gap-2 mb-2 bg-brand-bg-chat-input border border-brand-border rounded-lg px-3 py-1.5 focus-within:border-brand-green/40 transition-colors">
            <Navigation className="h-3 w-3 text-brand-green shrink-0" />
            <input
              value={steerInput}
              onChange={(e) => setSteerInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSteer();
                }
              }}
              placeholder="Steer the agent at the next step… (no abort)"
              className="flex-1 bg-transparent text-[11px] text-brand-green-soft placeholder:text-brand-green-muted outline-none font-mono"
            />
            <button
              onClick={handleSteer}
              disabled={!steerInput.trim()}
              className="p-1 rounded transition-colors disabled:opacity-40 text-brand-green hover:bg-brand-border"
              title="Inject steering message at next step"
            >
              <Send className="h-3 w-3" />
            </button>
          </div>
        )}
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
          {/* Textarea — wrapped in the right-click edit menu
              (Cut / Copy / Paste / Select all) */}
          <InputContextMenu textareaRef={textareaRef} value={input} onChange={setInput}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={chatMode === 'direct' ? 'Message LocalMind — chat mode, no tools…' : 'Message LocalMind, or describe a task to run…'}
              className="flex-1 bg-transparent text-[13px] text-brand-green-soft placeholder:text-brand-green-muted resize-none outline-none min-h-[22px] max-h-[160px] font-sans leading-relaxed"
              rows={1}
              disabled={isStreaming}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
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

            {/* Send / Abort */}
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

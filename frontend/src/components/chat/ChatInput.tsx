'use client';

import { useState, useRef, useEffect } from 'react';
import {
  Send,
  ChevronDown,
  Zap,
  Square,
  Navigation,
  MessageSquare,
  Bot,
} from 'lucide-react';

// B-2026-08-23-34: Chat mode options.
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
  modelName?: string;
  modelProvider?: string;
  /** Retained for the call site; no longer used since the per-message tool
   *  selector was removed (B-2026-08-24-3). */
  sessionId?: string;
  /** B-2026-08-23-34: Current chat mode. */
  chatMode?: string;
  /** B-2026-08-23-34: Callback to change chat mode. */
  onChatModeChange?: (mode: 'auto' | 'agent' | 'direct') => void;
}

export function ChatInput({ onSend, onAbort, onSteer, isStreaming, modelName, modelProvider, chatMode, onChatModeChange }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [steerInput, setSteerInput] = useState('');
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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
    // B-2026-08-23-34 + B-2026-08-24-3: the chat-mode picker (Auto/Agent/Chat)
    // replaced the old per-message tool/intent hint — send just the message.
    onSend(msg);
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
      <div className="px-4 pt-3 pb-2">
        {/* B-2026-08-02-5 (A5): steering without aborting — while the agent
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
        <div className="relative flex items-end gap-2 bg-brand-bg-rail border border-brand-border rounded-lg px-3 py-2 focus-within:border-brand-green/30 transition-colors">
          {/* Prompt symbol */}
          <span className="text-brand-green text-sm font-mono pb-0.5 shrink-0">&gt;</span>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={chatMode === 'direct' ? 'Ask LocalMind anything (Chat mode — no tools)...' : 'Ask LocalMind to build, debug, or explain...'}
            className="flex-1 bg-transparent text-[12px] text-brand-green-soft placeholder:text-brand-green-muted resize-none outline-none min-h-[20px] max-h-[120px] font-mono leading-relaxed"
            rows={1}
            disabled={isStreaming}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />

          {/* Action buttons */}
          <div className="flex items-center gap-1 shrink-0 pb-0.5">
            {/* B-2026-08-23-34: Chat mode picker */}
            {onChatModeChange && (
              <div className="relative" ref={modeMenuRef}>
                <button
                  onClick={() => setModeMenuOpen(!modeMenuOpen)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors disabled:opacity-40 ${
                    chatMode === 'direct'
                      ? 'text-brand-amber hover:text-brand-amber/80 hover:bg-brand-border'
                      : chatMode === 'agent'
                        ? 'text-blue-400 hover:text-blue-300 hover:bg-brand-border'
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
                className="p-1.5 rounded bg-brand-red text-white hover:bg-brand-red/80 transition-colors"
                title="Stop generating"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className={`p-1.5 rounded transition-colors ${
                  input.trim()
                    ? 'bg-brand-green text-brand-bg-base hover:bg-brand-green/80'
                    : 'bg-brand-border text-brand-green-muted'
                }`}
                title="Send message"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Footer hints */}
      <div className="flex items-center justify-between px-4 pb-2">
        <div className="flex items-center gap-3">
          <span className="text-[9px] text-brand-green-muted">
            <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted mr-0.5">⌘</kbd>
            <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted">Enter</kbd>
            {' '}to send
          </span>
          <span className="text-[9px] text-brand-green-muted">
            <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted mr-0.5">Shift</kbd>
            <kbd className="px-1 py-0.5 rounded bg-brand-border text-brand-green-muted">Enter</kbd>
            {' '}new line
          </span>
        </div>
        <span className="text-[9px] text-brand-green-muted">
          {modelName || 'Loading…'} · {modelProvider || '—'}
        </span>
      </div>
    </div>
  );
}

'use client';

import { useState, useRef, useEffect } from 'react';
import {
  Send,
  Paperclip,
  Mic,
  ChevronDown,
  Wrench,
  Zap,
  Command,
  Square,
} from 'lucide-react';

const toolOptions = [
  { id: 'auto', label: 'Auto', icon: <Zap className="h-3 w-3" /> },
  { id: 'file_write', label: 'File Write', icon: <Wrench className="h-3 w-3" /> },
  { id: 'code_exec', label: 'Code Exec', icon: <Command className="h-3 w-3" /> },
  { id: 'grep', label: 'Grep', icon: <Command className="h-3 w-3" /> },
  { id: 'shell', label: 'Shell', icon: <Command className="h-3 w-3" /> },
  { id: 'memory', label: 'Memory', icon: <Command className="h-3 w-3" /> },
];

interface ChatInputProps {
  onSend: (message: string) => void;
  onAbort: () => void;
  isStreaming: boolean;
  modelName?: string;
  modelProvider?: string;
}

export function ChatInput({ onSend, onAbort, isStreaming, modelName, modelProvider }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [selectedTool, setSelectedTool] = useState('auto');
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const toolMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (toolMenuRef.current && !toolMenuRef.current.contains(e.target as Node)) {
        setToolMenuOpen(false);
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

  const currentTool = toolOptions.find((t) => t.id === selectedTool)!;

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || isStreaming) return;
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

  return (
    <div className="border-t border-[#1a2a1a] bg-[#0a0f0a]">
      {/* Input area */}
      <div className="px-4 pt-3 pb-2">
        <div className="relative flex items-end gap-2 bg-[#111a11] border border-[#1a2a1a] rounded-lg px-3 py-2 focus-within:border-[#39d353]/30 transition-colors">
          {/* Prompt symbol */}
          <span className="text-[#39d353] text-sm font-mono pb-0.5 shrink-0">&gt;</span>

          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask LocalMind to build, debug, or explain..."
            className="flex-1 bg-transparent text-[12px] text-[#d4e8d4] placeholder:text-[#8ab08a] resize-none outline-none min-h-[20px] max-h-[120px] font-mono leading-relaxed"
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
            {/* Tool selector */}
            <div className="relative" ref={toolMenuRef}>
              <button
                onClick={() => setToolMenuOpen(!toolMenuOpen)}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-[#8ab08a] hover:text-[#d4e8d4] hover:bg-[#1a2a1a] transition-colors"
                disabled={isStreaming}
              >
                {currentTool.icon}
                <span>{currentTool.label}</span>
                <ChevronDown className="h-2.5 w-2.5" />
              </button>
              {toolMenuOpen && (
                <div className="absolute bottom-full right-0 mb-1 w-36 bg-[#111a11] border border-[#1a2a1a] rounded-md shadow-xl z-50 overflow-hidden">
                  <div className="p-1">
                    {toolOptions.map((tool) => (
                      <button
                        key={tool.id}
                        onClick={() => {
                          setSelectedTool(tool.id);
                          setToolMenuOpen(false);
                        }}
                        className="flex items-center gap-2 w-full px-2 py-1 rounded text-[10px] hover:bg-[#1a2a1a] transition-colors text-[#d4e8d4]"
                      >
                        {tool.icon}
                        <span>{tool.label}</span>
                        {tool.id === selectedTool && (
                          <span className="ml-auto text-[#39d353]">✓</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* File attach */}
            <button className="p-1 rounded text-[#8ab08a] hover:text-[#d4e8d4] hover:bg-[#1a2a1a] transition-colors">
              <Paperclip className="h-3.5 w-3.5" />
            </button>

            {/* Voice input */}
            <button className="p-1 rounded text-[#8ab08a] hover:text-[#d4e8d4] hover:bg-[#1a2a1a] transition-colors">
              <Mic className="h-3.5 w-3.5" />
            </button>

            {/* Send / Abort */}
            {isStreaming ? (
              <button
                onClick={handleAbort}
                className="p-1.5 rounded bg-[#e05555] text-white hover:bg-[#e05555]/80 transition-colors"
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
                    ? 'bg-[#39d353] text-[#0a0f0a] hover:bg-[#39d353]/80'
                    : 'bg-[#1a2a1a] text-[#8ab08a]'
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
          <span className="text-[9px] text-[#8ab08a]">
            <kbd className="px-1 py-0.5 rounded bg-[#1a2a1a] text-[#8ab08a] mr-0.5">⌘</kbd>
            <kbd className="px-1 py-0.5 rounded bg-[#1a2a1a] text-[#8ab08a]">Enter</kbd>
            {' '}to send
          </span>
          <span className="text-[9px] text-[#8ab08a]">
            <kbd className="px-1 py-0.5 rounded bg-[#1a2a1a] text-[#8ab08a] mr-0.5">Shift</kbd>
            <kbd className="px-1 py-0.5 rounded bg-[#1a2a1a] text-[#8ab08a]">Enter</kbd>
            {' '}new line
          </span>
        </div>
        <span className="text-[9px] text-[#8ab08a]">
          {modelName || 'Loading…'} · {modelProvider || '—'}
        </span>
      </div>
    </div>
  );
}

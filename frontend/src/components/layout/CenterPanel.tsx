'use client';

import { useRef, useEffect } from 'react';
import {
  Cpu,
  Brain,
  Wrench,
  Wifi,
  WifiOff,
  Shield,
  Zap,
  Loader2,
} from 'lucide-react';
import { ChatMessage as ChatMessageType, ModelOption } from '@/types';
import { ChatMessage } from '@/components/chat/ChatMessage';
import { ChatInput } from '@/components/chat/ChatInput';

// Human-readable labels for intent values shown in the header badge.
// Previously the raw snake_case value (e.g. "code", "general_question")
// was displayed directly — inconsistent with the Observability tab.
const INTENT_LABELS: Record<string, string> = {
  code: 'Code',
  file: 'File',
  chat: 'Chat',
  search: 'Search',
  shell: 'Shell',
  memory: 'Memory',
  general_question: 'Chat',
  general: 'Chat',
};

interface HealthState {
  status: 'online' | 'offline' | 'checking';
  version?: string;
  uptime?: number;
}

interface CenterPanelProps {
  messages: ChatMessageType[];
  selectedModel: ModelOption;
  isStreaming: boolean;
  health: HealthState;
  onSend: (message: string, tool?: string) => void;
  onAbort: () => void;
  currentIntent?: string;
  currentConfidence?: number;
  memoryCount: number;
  sessionId?: string;
}

export function CenterPanel({
  messages,
  selectedModel,
  isStreaming,
  health,
  onSend,
  onAbort,
  currentIntent,
  currentConfidence,
  memoryCount,
  sessionId,
}: CenterPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const isOnline = health.status === 'online';
  const confidencePercent = currentConfidence
    ? Math.round(currentConfidence * 100)
    : null;

  // Clean up model name for display: remove internal suffixes, format nicely
  const rawModelName = selectedModel?.name || selectedModel?.id || '';
  const displayModelName = rawModelName
    ? rawModelName
        .replace(/\s*-\s*zen$/i, '')
        .replace(/\s*-\s*local$/i, '')
        .replace(/^ollama[:/]/, '')
        .replace(/_/g, ' ')
        .replace(/^\w/, c => c.toUpperCase())
        .trim()
    : 'Connecting…';

  return (
    <div className="h-full flex flex-col bg-[#0a0f0a]">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#1a2a1a] bg-[#0a0f0a]">
        <div className="flex items-center gap-3">
          <h1 className="text-[12px] font-medium text-[#d4e8d4]">
            LocalMind Assistant
          </h1>
          {/* Model badge — green pill showing the active model */}
          <span
            className="text-[9px] px-2 py-0.5 rounded-full bg-[#39d353]/15 text-[#39d353] border border-[#39d353]/20 font-mono truncate max-w-[180px]"
            title={`Model: ${selectedModel?.name || selectedModel?.id}`}
          >
            {displayModelName}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Confidence badge */}
          {confidencePercent !== null && (
            <div className="flex items-center gap-1.5" title={`Confidence: ${confidencePercent}%`}>
              <Zap className="h-3 w-3 text-[#39d353]" />
              <span className="text-[10px] text-[#8ab08a]">{confidencePercent}%</span>
            </div>
          )}
          {/* Memory badge */}
          <div className="flex items-center gap-1.5" title={`Memory: ${memoryCount} facts loaded`}>
            <Brain className="h-3 w-3 text-[#e8a420]" />
            <span className="text-[10px] text-[#8ab08a]">{memoryCount}</span>
          </div>
          {/* Intent badge */}
          {currentIntent && (
            <div className="flex items-center gap-1.5" title={`Intent: ${currentIntent}`}>
              <Wrench className="h-3 w-3 text-[#8ab08a]" />
              <span className="text-[10px] text-[#8ab08a]">
                {INTENT_LABELS[currentIntent] || currentIntent}
              </span>
            </div>
          )}
          <div className="w-px h-3 bg-[#1a2a1a]" />
          {/* Online/offline status */}
          <div className="flex items-center gap-1" title={isOnline ? 'Online' : 'Offline'}>
            {isOnline ? (
              <Wifi className="h-3 w-3 text-[#39d353]" />
            ) : (
              <WifiOff className="h-3 w-3 text-[#e05555]" />
            )}
          </div>
          <div className="flex items-center gap-1" title="Local execution">
            <Shield className="h-3 w-3 text-[#39d353]" />
            <span className="text-[9px] text-[#8ab08a]">Local</span>
          </div>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar min-w-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
            <div className="w-12 h-12 rounded-xl bg-[#39d353]/10 flex items-center justify-center">
              <Cpu className="h-6 w-6 text-[#39d353]" />
            </div>
            <div>
              <h2 className="text-sm font-medium text-[#d4e8d4] mb-1">
                Welcome to LocalMind
              </h2>
              <p className="text-[11px] text-[#8ab08a] max-w-sm">
                Your local AI assistant. Ask me to build, debug, explain, or refactor code.
                I can read files, run commands, search code, and more.
              </p>
            </div>
          </div>
        )}

        <div className="divide-y divide-[#1a2a1a]/50 overflow-hidden">
          {messages.map((msg) => (
            <ChatMessage key={msg.id} message={msg} isStreaming={isStreaming && msg === messages[messages.length - 1] && msg.role === 'assistant'} />
          ))}
        </div>

        {/* Streaming indicator — only show when assistant content is still empty */}
        {/* Session 30: replace static "Thinking..." with real pipeline status. */}
        {/* The engine emits status_update events ("Let me search the web...", */}
        {/* "Understanding your request...", etc.) — show those instead of a */}
        {/* dead "Thinking..." label. Only show "Thinking" when the model is */}
        {/* actually reasoning (thinking_token events fill message.thinking). */}
        {isStreaming && (() => {
          const lastMsg = messages[messages.length - 1];
          const hasContent = lastMsg && lastMsg.role === 'assistant' && lastMsg.content && lastMsg.content.trim().length > 0;
          const hasToolCalls = lastMsg && lastMsg.role === 'assistant' && lastMsg.toolCalls && lastMsg.toolCalls.length > 0;
          const hasThinking = lastMsg && lastMsg.role === 'assistant' && lastMsg.thinking && lastMsg.thinking.trim().length > 0;
          // If there's content or tool calls already visible in the message,
          // don't show the separate indicator — the message itself is the feedback.
          if (hasContent || hasToolCalls) return null;
          // Get the status text — prefer the real pipeline status, fall back
          // to "Thinking" only if the model is actually reasoning, otherwise
          // "Working on it..." as the initial acknowledgment.
          const statusText = lastMsg?.statusText || (hasThinking ? 'Thinking' : 'Working on it...');
          return (
            <div className="px-4 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="h-3 w-3 text-[#39d353] animate-spin" />
                <span className="text-[10px] text-[#8ab08a]">{statusText}</span>
                <span className="flex gap-0.5">
                  <span className="w-1 h-1 bg-[#39d353] rounded-full animate-bounce [animation-delay:0ms]" />
                  <span className="w-1 h-1 bg-[#39d353] rounded-full animate-bounce [animation-delay:150ms]" />
                  <span className="w-1 h-1 bg-[#39d353] rounded-full animate-bounce [animation-delay:300ms]" />
                </span>
              </div>
            </div>
          );
        })()}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <ChatInput
        onSend={onSend}
        onAbort={onAbort}
        isStreaming={isStreaming}
        modelName={selectedModel.name}
        modelProvider={selectedModel.provider}
        sessionId={sessionId}
      />
    </div>
  );
}

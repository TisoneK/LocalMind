'use client';

import { useEffect, useState } from 'react';
import { FileText, Loader2, AlertTriangle, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { localmindClient } from '@/lib/localmind/client';
import type { FileContent } from '@/types';

interface FilePreviewDialogProps {
  /** Absolute path of the file to preview; null/empty closes the dialog. */
  path: string | null;
  onClose: () => void;
}

// Code-like extensions get monospace rendering; everything else is prose text
// (office docs are already flattened to text server-side).
const _CODE_EXTS = new Set([
  'py', 'js', 'ts', 'tsx', 'jsx', 'json', 'yaml', 'yml', 'toml', 'ini',
  'cfg', 'env', 'sh', 'bash', 'rs', 'go', 'java', 'c', 'h', 'cpp', 'hpp',
  'html', 'xml', 'css', 'sql', 'log',
]);

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FilePreviewDialog({ path, onClose }: FilePreviewDialogProps) {
  const [content, setContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setContent(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent(null);
    localmindClient.getFileContent(path).then((data) => {
      if (cancelled) return;
      setLoading(false);
      if (!data) {
        setError('Could not read this file. It may have been moved or deleted.');
        return;
      }
      setContent(data);
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const isImage = !!content?.image_data_url;
  const isMarkdown = content?.extension === 'md' || content?.extension === 'markdown';
  const isCode = !isMarkdown && !!content?.extension && _CODE_EXTS.has(content.extension);
  const bodyText = content?.text ?? '';

  return (
    <Dialog open={!!path} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col overflow-hidden">
        <DialogHeader className="flex-row items-center justify-between space-y-0 pr-8">
          <DialogDescription className="sr-only">
            File preview: {content?.name ?? path ?? ''}
          </DialogDescription>
          <DialogTitle className="flex items-center gap-2 text-sm font-mono">
            <FileText className="h-4 w-4 text-brand-green" />
            {content?.name ?? path?.split('/').pop() ?? ''}
            {content && (
              <span className="text-[10px] text-brand-green-muted font-normal">
                {formatSize(content.size)}
                {content.truncated && ' · truncated'}
              </span>
            )}
          </DialogTitle>
          <button
            onClick={onClose}
            className="absolute right-3 top-3 rounded p-1 text-brand-green-muted hover:text-brand-green hover:bg-brand-border/50 transition-colors"
            aria-label="Close preview"
          >
            <X className="h-4 w-4" />
          </button>
        </DialogHeader>

        <div className="flex-1 overflow-auto min-h-0 border-t border-brand-border/60">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-12 text-brand-green-muted text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          )}
          {!loading && error && (
            <div className="flex items-center gap-2 px-4 py-6 text-brand-red text-sm">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
          {!loading && !error && isImage && content?.image_data_url && (
            <div className="flex justify-center p-4">
              {/* The browser is the renderer for these inline data URLs. */}
              <img
                src={content.image_data_url}
                alt={content.name}
                className="max-w-full max-h-[60vh] object-contain rounded border border-brand-border"
              />
            </div>
          )}
          {!loading && !error && !isImage && isMarkdown && (
            <div className="px-4 py-3 text-xs text-brand-green-soft leading-relaxed overflow-hidden max-w-full break-words">
              <ReactMarkdown>{bodyText}</ReactMarkdown>
            </div>
          )}
          {!loading && !error && !isImage && !isMarkdown && (
            <pre
              className={`px-4 py-3 text-xs leading-relaxed whitespace-pre-wrap break-words ${
                isCode
                  ? 'font-mono text-brand-green-soft'
                  : 'font-sans text-brand-green-soft'
              }`}
            >
              {bodyText || '(empty file)'}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

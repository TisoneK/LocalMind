'use client';

import { useEffect, useState } from 'react';
import { FileText, Loader2, AlertTriangle, X, Pencil, Check, RotateCcw } from 'lucide-react';
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
  // Edit mode (B-2026-08-23-6 follow-up): only for text/code files, saved back
  // through the same POST /api/confirm-write permission gate the agent uses.
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

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
    setIsEditing(false);
    setSaveError(null);
    setSavedFlash(false);
    localmindClient.getFileContent(path).then((data) => {
      if (cancelled) return;
      setLoading(false);
      if (!data) {
        setError('Could not read this file. It may have been moved or deleted.');
        return;
      }
      setContent(data);
      setDraft(data.text ?? '');
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const isImage = !!content?.image_data_url;
  const isMarkdown = content?.extension === 'md' || content?.extension === 'markdown';
  const isCode = !isMarkdown && !!content?.extension && _CODE_EXTS.has(content.extension);
  const bodyText = content?.text ?? '';
  const canEdit = !!content && content.editable === true && !isImage;

  const handleSave = async () => {
    if (!path || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await localmindClient.confirmWrite(path, draft);
      setSaving(false);
      setIsEditing(false);
      setSavedFlash(true);
      // Refresh size + text from disk so the preview matches the saved file.
      const fresh = await localmindClient.getFileContent(path);
      if (fresh) {
        setContent(fresh);
        setDraft(fresh.text ?? '');
      }
      setTimeout(() => setSavedFlash(false), 2500);
    } catch {
      setSaving(false);
      setSaveError('Save failed. The file may be outside allowed folders or locked.');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      void handleSave();
    }
  };

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
          <div className="flex items-center gap-1.5">
            {savedFlash && (
              <span className="text-[10px] text-brand-green flex items-center gap-1 mr-1">
                <Check className="h-3 w-3" />
                Saved
              </span>
            )}
            {canEdit && !isEditing && (
              <button
                onClick={() => {
                  setDraft(content?.text ?? '');
                  setSaveError(null);
                  setIsEditing(true);
                }}
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] border border-brand-border text-brand-green-muted hover:text-brand-green hover:border-brand-green/40 transition-colors"
              >
                <Pencil className="h-3 w-3" />
                Edit
              </button>
            )}
            {canEdit && isEditing && (
              <>
                <button
                  onClick={() => {
                    setIsEditing(false);
                    setDraft(content?.text ?? '');
                    setSaveError(null);
                  }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-[10px] border border-brand-border text-brand-green-muted hover:text-brand-green transition-colors"
                >
                  <RotateCcw className="h-3 w-3" />
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1 px-2 py-1 rounded text-[10px] border border-brand-green bg-brand-green/10 text-brand-green hover:brightness-125 transition-colors disabled:opacity-40"
                >
                  {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </>
            )}
            <button
              onClick={onClose}
              className="rounded p-1 text-brand-green-muted hover:text-brand-green hover:bg-brand-border/50 transition-colors"
              aria-label="Close preview"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
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
          {!loading && !error && !isImage && isMarkdown && !isEditing && (
            <div className="px-4 py-3 text-xs text-brand-green-soft leading-relaxed overflow-hidden max-w-full break-words">
              <ReactMarkdown>{bodyText}</ReactMarkdown>
            </div>
          )}
          {!loading && !error && !isImage && !isMarkdown && !isEditing && (
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
          {!loading && !error && !isImage && isEditing && (
            <div className="flex flex-col h-full">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                spellCheck={false}
                className="flex-1 min-h-[50vh] w-full resize-none bg-transparent px-4 py-3 text-xs font-mono text-brand-green-soft leading-relaxed outline-none focus:ring-0"
                aria-label="Edit file content"
              />
              {saveError && (
                <div className="flex items-center gap-2 px-4 py-2 text-brand-red text-xs border-t border-brand-border/60">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  {saveError}
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

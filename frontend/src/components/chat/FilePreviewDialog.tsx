'use client';

import { useEffect, useState } from 'react';
import { FileText, Loader2, AlertTriangle, X, Pencil, Check, RotateCcw, Table as TableIcon, Eye, GitPullRequest } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { localmindClient } from '@/lib/localmind/client';
import { DiffBlock } from '@/components/shared/DiffBlock';
import type { DiffData, FileContent } from '@/types';

type PreviewMode = 'preview' | 'edit' | 'diff';

interface FilePreviewDialogProps {
  /** Absolute path of the file to preview; null/empty closes the dialog. */
  path: string | null;
  onClose: () => void;
  /** Diff hunks captured from edit_file results this turn,
   *  keyed by absolute path — powers the Diff mode (before/after). */
  diffs?: Record<string, DiffData>;
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

export function FilePreviewDialog({ path, onClose, diffs }: FilePreviewDialogProps) {
  const [content, setContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Preview / Edit / Diff mode switcher. Edit mode (text/code files AND spreadsheet cells, saved
  // back through the same POST /api/confirm-write gate the agent uses (text
  // via `content`, spreadsheets via the structured `sheets` payload). Diff
  // shows the edit_file hunks captured this turn (DiffBlock).
  const [mode, setMode] = useState<PreviewMode>('preview');
  const isEditing = mode === 'edit';
  const [draft, setDraft] = useState('');
  const [draftSheets, setDraftSheets] = useState<{ name: string; rows: string[][]; truncated?: boolean }[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  // Spreadsheet tab (CSV/XLSX) — reset whenever a different file opens.
  const [activeSheet, setActiveSheet] = useState(0);

  useEffect(() => {
    // Closing (path → null): keep the last file on screen so the fade-out doesn't
    // flash an empty body. The next open resets everything below.
    if (!path) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent(null);
    setMode('preview');
    setSaveError(null);
    setSavedFlash(false);
    setActiveSheet(0);
    setDraftSheets([]);
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
  const sheets = content?.sheets ?? [];
  // Spreadsheet cells are editable only when NO sheet was truncated — saving a
  // capped grid would silently delete the rows the preview didn't load.
  const canEditSpreadsheet = sheets.length > 0 && !sheets.some((s) => s.truncated);
  const canEditText = !!content && content.editable === true && !isImage && sheets.length === 0;
  const canEdit = canEditText || canEditSpreadsheet;
  const isSpreadsheet = sheets.length > 0;
  // The diff for THIS file, captured from edit_file results
  // this turn (latest wins). Diff mode is offered only when hunks exist.
  // Windows-tolerance: the hook normalizes keys to forward slashes.
  const fileDiff = path ? diffs?.[path] ?? diffs?.[path.split('\\').join('/')] : undefined;
  const hasDiff = !!fileDiff && fileDiff.hunks.length > 0;
  // In edit mode cells are edited in the draft copy; otherwise show the server rows.
  const viewSheets = isEditing && draftSheets.length > 0 ? draftSheets : sheets;
  const activeRows = viewSheets[activeSheet]?.rows ?? [];

  const startEdit = () => {
    setSaveError(null);
    if (isSpreadsheet) {
      setDraftSheets(sheets.map((s) => ({ name: s.name, rows: s.rows.map((r) => [...r]) })));
    } else {
      setDraft(content?.text ?? '');
    }
    setMode('edit');
  };

  const cancelEdit = () => {
    setMode('preview');
    setSaveError(null);
    setDraft(content?.text ?? '');
    setDraftSheets([]);
  };

  const setCell = (rowIdx: number, colIdx: number, value: string) => {
    setDraftSheets((prev) =>
      prev.map((s, si) =>
        si === activeSheet
          ? {
              ...s,
              rows: s.rows.map((r, ri) =>
                ri === rowIdx ? r.map((c, ci) => (ci === colIdx ? value : c)) : r
              ),
            }
          : s
      )
    );
  };

  const handleSave = async () => {
    if (!path || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (isSpreadsheet) {
        await localmindClient.confirmWrite(
          path,
          '',
          draftSheets.map((s) => ({ name: s.name, rows: s.rows }))
        );
      } else {
        await localmindClient.confirmWrite(path, draft);
      }
      setSaving(false);
      setMode('preview');
      setSavedFlash(true);
      // Refresh size + content from disk so the preview matches the saved file.
      const fresh = await localmindClient.getFileContent(path);
      if (fresh) {
        setContent(fresh);
        setDraft(fresh.text ?? '');
        setDraftSheets([]);
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
            {canEdit && isEditing && (
              <>
                <button
                  onClick={cancelEdit}
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

        {/* Preview / Edit / Diff mode switcher */}
        {(canEdit || hasDiff) && (
          <div className="flex items-center gap-0.5 px-2 pt-1.5 pb-0 border-b border-brand-border/60 shrink-0">
            <button
              onClick={() => setMode('preview')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] transition-colors ${
                mode === 'preview'
                  ? 'bg-brand-green/10 text-brand-green'
                  : 'text-brand-green-muted hover:text-brand-green'
              }`}
              data-testid="preview-mode-preview"
            >
              <Eye className="h-3 w-3" />
              Preview
            </button>
            {canEdit && (
              <button
                onClick={() => (isEditing ? cancelEdit() : startEdit())}
                className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] transition-colors ${
                  isEditing
                    ? 'bg-brand-green/10 text-brand-green'
                    : 'text-brand-green-muted hover:text-brand-green'
                }`}
                data-testid="preview-mode-edit"
              >
                <Pencil className="h-3 w-3" />
                Edit
              </button>
            )}
            {hasDiff && (
              <button
                onClick={() => { if (isEditing) cancelEdit(); setMode('diff'); }}
                className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] transition-colors ${
                  mode === 'diff'
                    ? 'bg-brand-green/10 text-brand-green'
                    : 'text-brand-green-muted hover:text-brand-green'
                }`}
                data-testid="preview-mode-diff"
              >
                <GitPullRequest className="h-3 w-3" />
                Diff
              </button>
            )}
          </div>
        )}

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
          {!loading && !error && mode !== 'diff' && sheets.length > 0 && (
            <div className="flex flex-col h-full">
              {/* Sheet tabs */}
              <div className="flex items-center gap-0.5 px-2 pt-2 overflow-x-auto border-b border-brand-border/60 shrink-0">
                {sheets.map((s, i) => (
                  <button
                    key={s.name + i}
                    onClick={() => setActiveSheet(i)}
                    className={`flex items-center gap-1 px-3 py-1.5 rounded-t text-[11px] border-b-2 transition-colors shrink-0 ${
                      i === activeSheet
                        ? 'text-brand-green border-brand-green bg-brand-green/5'
                        : 'text-brand-green-muted border-transparent hover:text-brand-green'
                    }`}
                  >
                    <TableIcon className="h-3 w-3" />
                    {s.name}
                    {s.truncated && <span className="text-[9px] opacity-60">…</span>}
                  </button>
                ))}
              </div>
              {/* Data table */}
              <div className="flex-1 overflow-auto min-h-0">
                <table className="border-collapse text-xs w-max min-w-full">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-brand-bg-code">
                      <th className="px-2 py-1.5 text-[10px] text-brand-green-muted font-mono border-b border-brand-border text-left">#</th>
                      {activeRows[0]?.map((h, i) => (
                        <th
                          key={i}
                          className="px-2 py-1.5 text-[10px] text-brand-green font-mono uppercase border-b border-brand-border text-left whitespace-nowrap"
                        >
                          {h || `Col ${i + 1}`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {activeRows.slice(1).map((row, ri) => (
                      <tr key={ri} className="hover:bg-brand-border/30">
                        <td className="px-2 py-1 text-[10px] text-brand-green-muted font-mono border-b border-brand-border/40 text-right select-none">
                          {ri + 1}
                        </td>
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className="px-0.5 py-0 text-xs text-brand-green-soft border-b border-brand-border/40 max-w-[320px]"
                          >
                            {isEditing ? (
                              <input
                                value={cell}
                                onChange={(e) => setCell(ri + 1, ci, e.target.value)}
                                spellCheck={false}
                                aria-label={`Cell ${ri + 1},${ci + 1}`}
                                className="w-full min-w-[80px] bg-transparent px-1.5 py-1 text-xs text-brand-green-soft outline-none focus:bg-brand-green/5 focus:ring-1 focus:ring-brand-green/40 rounded truncate"
                              />
                            ) : (
                              <span
                                title={cell}
                                className="block px-1.5 py-1 truncate"
                              >
                                {cell || '\u00A0'}
                              </span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {activeRows.length === 0 && (
                  <div className="px-4 py-6 text-brand-green-muted text-xs">(empty sheet)</div>
                )}
              </div>
              {viewSheets[activeSheet]?.truncated && (
                <div className="px-3 py-1.5 text-[10px] text-brand-amber border-t border-brand-border/60 shrink-0">
                  Rows/columns truncated for preview — open the file to see everything.
                </div>
              )}
            </div>
          )}
          {!loading && !error && mode === 'preview' && isImage && content?.image_data_url && (
            <div className="flex justify-center p-4">
              {/* The browser is the renderer for these inline data URLs. */}
              <img
                src={content.image_data_url}
                alt={content.name}
                className="max-w-full max-h-[60vh] object-contain rounded border border-brand-border"
              />
            </div>
          )}
          {!loading && !error && mode === 'preview' && !isImage && isMarkdown && (
            <div className="px-4 py-3 text-xs text-brand-green-soft leading-relaxed overflow-hidden max-w-full break-words">
              <ReactMarkdown>{bodyText}</ReactMarkdown>
            </div>
          )}
          {!loading && !error && mode === 'preview' && !isImage && !isMarkdown && !isSpreadsheet && (
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
          {!loading && !error && mode === 'diff' && hasDiff && (
            <div className="p-2" data-testid="preview-diff-pane">
              <DiffBlock
                hunks={fileDiff!.hunks}
                language={fileDiff!.language}
                showActions={false}
              />
            </div>
          )}
          {!loading && !error && mode === 'diff' && !hasDiff && (
            <div className="px-4 py-6 text-xs text-brand-green-muted">
              No edits recorded for this file this turn.
            </div>
          )}
          {!loading && !error && !isImage && isEditing && !isSpreadsheet && (
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

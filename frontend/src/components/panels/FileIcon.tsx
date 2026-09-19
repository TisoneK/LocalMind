import { File, FileCode, FileJson, FileText } from 'lucide-react';

/** One icon per file type, shared by every file list so they read the same. */
export function FileIcon({ name, className = 'h-3.5 w-3.5' }: { name: string; className?: string }) {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['ts', 'tsx', 'js', 'jsx', 'py', 'go', 'rs', 'java', 'c', 'cpp', 'sh'].includes(ext)) {
    return <FileCode className={`${className} text-brand-green`} aria-hidden />;
  }
  if (ext === 'json') return <FileJson className={`${className} text-brand-amber`} aria-hidden />;
  if (['md', 'txt', 'csv', 'log'].includes(ext)) return <FileText className={`${className} text-brand-green-muted`} aria-hidden />;
  if (['env', 'example'].includes(ext)) return <File className={`${className} text-brand-amber`} aria-hidden />;
  return <File className={`${className} text-brand-green-muted`} aria-hidden />;
}

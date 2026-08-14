'use client';

import { useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  FolderOpen,
  FileCode,
  FileText,
  FileJson,
} from 'lucide-react';
import { FileNode } from '@/types';

interface FileExplorerProps {
  files: FileNode[];
  onFileOpen?: (path: string) => void;
}

function getFileIcon(name: string) {
  const ext = name.split('.').pop() || '';
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) return <FileCode className="h-3.5 w-3.5 text-brand-green" />;
  if (['json'].includes(ext)) return <FileJson className="h-3.5 w-3.5 text-brand-amber" />;
  if (['md', 'txt'].includes(ext)) return <FileText className="h-3.5 w-3.5 text-brand-green-muted" />;
  if (['env', 'example'].includes(ext)) return <File className="h-3.5 w-3.5 text-brand-amber" />;
  return <File className="h-3.5 w-3.5 text-brand-green-muted" />;
}

function FileTreeNode({ node, depth = 0, onFileOpen }: { node: FileNode; depth?: number; onFileOpen?: (path: string) => void }) {
  const [expanded, setExpanded] = useState(node.expanded ?? false);

  if (node.type === 'file') {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-0.5 hover:bg-brand-border/50 cursor-pointer rounded transition-colors group"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onFileOpen?.(node.path)}
        title={node.path}
      >
        {getFileIcon(node.name)}
        <span className="text-[11px] text-brand-green-soft truncate group-hover:text-brand-green transition-colors">
          {node.name}
        </span>
      </div>
    );
  }

  return (
    <div>
      <div
        className="flex items-center gap-1 px-2 py-0.5 hover:bg-brand-border/50 cursor-pointer rounded transition-colors group"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-brand-green-muted shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0" />
        )}
        {expanded ? (
          <FolderOpen className="h-3.5 w-3.5 text-brand-amber shrink-0" />
        ) : (
          <Folder className="h-3.5 w-3.5 text-brand-amber shrink-0" />
        )}
        <span className="text-[11px] text-brand-green-soft truncate font-medium group-hover:text-brand-green transition-colors">
          {node.name}
        </span>
      </div>
      {expanded && (
        node.children && node.children.length > 0 ? (
          <div>
            {node.children.map((child) => (
              <FileTreeNode key={child.path} node={child} depth={depth + 1} onFileOpen={onFileOpen} />
            ))}
          </div>
        ) : (
          <div className="text-[10px] text-brand-green-faint italic px-2 py-0.5" style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}>
            Empty
          </div>
        )
      )}
    </div>
  );
}

export function FileExplorer({ files, onFileOpen }: FileExplorerProps) {
  return (
    <div className="space-y-0.5">
      {files.map((node) => (
        <FileTreeNode key={node.path} node={node} onFileOpen={onFileOpen} />
      ))}
    </div>
  );
}

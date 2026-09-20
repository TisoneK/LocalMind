/** ToolIcon — the colour-coded glyph for a tool (see lib/localmind/toolIconMeta.ts). */

import { toolIconMeta } from '@/lib/localmind/toolIconMeta';

export function ToolIcon({ name, className = 'h-3 w-3' }: { name: string | undefined; className?: string }) {
  const { Icon, tone, kind } = toolIconMeta(name);
  return <Icon className={`${className} shrink-0 ${tone}`} aria-label={kind} data-tool-kind={kind} />;
}

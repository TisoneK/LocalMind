/**
 * Reduce a markdown string to plain single-line text for compact previews
 * (session list rows, tooltips). Pure string transforms, no DOM — kept here
 * so the strip rules are unit-testable against the shapes real replies
 * contain (bold, tables, links, code fences).
 *
 * The stored message text is NEVER modified — this is a display-time render
 * for one-line previews where markdown syntax reads as noise.
 */
export function stripMarkdownToPreview(md: string): string {
  if (!md) return '';
  let text = md;
  // Fenced code blocks first (their content would otherwise leak markers).
  text = text.replace(/```[\s\S]*?```/g, ' ');
  // Inline code keeps its content, drops the backticks.
  text = text.replace(/`([^`]*)`/g, '$1');
  // Images and links: keep only the label text.
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ');
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
  // Line-level syntax: headers, blockquotes, list bullets.
  text = text.replace(/^\s{0,3}#{1,6}\s+/gm, '');
  text = text.replace(/^\s{0,3}>\s?/gm, '');
  text = text.replace(/^\s*[-*+]\s+/gm, '');
  // Tables: drop separator rows (|---|:---:) entirely; content rows keep
  // their cell text with the pipes as plain spacing.
  text = text
    .split('\n')
    .map((line) => {
      if (!line.includes('|')) return line;
      if (/^[\s|:-]+$/.test(line) && line.includes('-')) return '';
      return line.replace(/\|/g, ' ');
    })
    .join('\n');
  // Emphasis markers.
  text = text.replace(/(\*\*|__)(.*?)\1/g, '$2');
  text = text.replace(/(\*|_)(.*?)\1/g, '$2');
  text = text.replace(/~~(.*?)~~/g, '$1');
  // Collapse to one line.
  return text.replace(/\s+/g, ' ').trim();
}

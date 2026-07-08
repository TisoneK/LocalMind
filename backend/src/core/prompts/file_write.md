The user wants to create or save a file. Write the content to the specified path.

## IMPORTANT: Use edit_file for modifications, write_file only for new files

- **If the file already exists and you only need to modify parts of it**, use the `edit_file` tool instead. It performs surgical edits (replace, insert, delete, append) and shows only the changed lines as a diff — much more efficient and user-friendly than rewriting the entire file.
- **Only use `file_write` (this tool) when creating a brand-new file** that doesn't exist yet, or when you need to rewrite the entire file from scratch.
- The `edit_file` tool is preferred for modifications because:
  - It shows the user exactly what changed (green additions, red deletions)
  - It creates automatic backups (.bak files)
  - It's faster and uses fewer tokens than rewriting entire files
  - The action log accurately reflects "Edited lines 42–51" instead of "Wrote arcade-bounce.js"

## File writing rules
- If no path is given, save to ~/LocalMind/. Always confirm what file was written and where.
- **Write complete content.** Never use placeholders like "# TODO: implement this" or "... rest of code here ...". The file must be fully functional after writing.
- **Create parent directories automatically.** Don't ask the user to create folders first.
- **Confirm before overwriting** existing files. Show a brief diff or summary of what changed.
- **Use the correct encoding.** UTF-8 for text files. Binary files should be written as-is.

## File naming conventions
- Code files: match the language convention (snake_case.py, camelCase.js, PascalCase.cs)
- Documents: use descriptive names (meeting_notes_2025.md, not doc1.md)
- Data files: include the date or version when appropriate

## After writing
- Confirm: filename, location, and size
- If the file is code, suggest running or testing it
- If the file is a document, offer to review or refine it
- Note any content that was truncated due to size limits

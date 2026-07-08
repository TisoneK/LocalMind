# 03 — File Handling

## Mental model

```
~/LocalMind/          ← scratch space (LM's working directory)
~/Documents/Reviews/  ← user's destination (final output)
```

LocalMind never writes final output directly to the user's destination.
It always works through the scratch space first, then copies back.

## Write flow

```
User: "process CV.pdf and save to Desktop/Reviews/"
         │
         ▼
1. Resolve final_dest   → ~/Desktop/Reviews/CV_20260504_143022.pdf
   (PathUnresolvableError if path can't be anchored — never silent redirect)
         │
         ▼
2. Write to scratch     → ~/LocalMind/CV.pdf
   (cleanup_cache() runs here — removes stale entries before writing)
         │
         ▼
3. Copy-back to dest    → ~/Desktop/Reviews/CV_20260504_143022.pdf
   (original CV.pdf at destination is untouched)
         │
         ▼
4. Return result        content="{filename} - {dest_parent}/"
                        metadata.path = final dest
                        metadata.cache_path = scratch path
```

## Scratch space rules

- `~/LocalMind/` is the **only** directory LocalMind writes to during processing
- Files stay in scratch until they age out (see Cache policy below)
- The DB (`localmind.db`, `*.db-shm`, `*.db-wal`) and `uploads/` are
  never touched by cleanup — they are not cache

## Copy-back and rename rules

| Situation | Behaviour |
|---|---|
| No destination given | File stays in `~/LocalMind/` — no copy-back |
| Document format, no user-specified name | Timestamp-rename at dest: `CV_20260504_143022.pdf` |
| Code/data format, no user-specified name | Copy as-is: `main.py` → `main.py` |
| User explicitly named the output | Copy as-is, skip rename entirely |

### Document formats (timestamp rename)

MS Office/Windows: `.pdf` `.docx` `.doc` `.xlsx` `.xls` `.pptx` `.ppt`
`.pub` `.accdb` `.mdb`

Images: `.png` `.jpg` `.jpeg` `.gif` `.bmp` `.webp` `.svg` `.tiff` `.tif`
`.ico` `.heic` `.raw`

LibreOffice: `.odt` `.ods` `.odp` `.odg`

Other: `.epub` `.rtf`

### Code/data formats (no rename)

Everything else: `.py` `.js` `.ts` `.md` `.json` `.csv` `.txt` `.html`
`.css` `.sh` `.yaml` `.toml` `.sql` `.rs` `.go` and all other extensions
not listed above.

## Version control semantics

The timestamp rename is intentional version-control behaviour:

```
Desktop/Reviews/
  CV.pdf                        ← original, untouched
  CV_20260504_143022.pdf        ← first processed version
  CV_20260505_091500.pdf        ← second processed version
```

The user's source of truth is never overwritten. Every processed output is
a new versioned file. The user decides what to keep.

## Path resolution

`resolve_write_path(raw_path)` is the single canonical resolver. It handles:

1. Named-folder shorthand — `"Documents"` → `~/Documents/`
2. Home-relative — `"~/projects/foo.py"`
3. Cross-OS absolute — `"C:\Users\tison\Documents\Code\foo.py"` on Linux
4. Native absolute — `"/home/tison/Documents/foo.py"`
5. Relative with known anchor — `"Documents/Code/foo.py"` → `~/Documents/Code/foo.py`

If none of the above match, `PathUnresolvableError` is raised with an optional
fuzzy suggestion. **There is no silent fallback to `~/LocalMind/`** when the
user gave an explicit path.

The only time `~/LocalMind/` is used as the destination is when the user
gave **no path at all**.

### Known folders

The resolver's anchor set is defined in `_NAMED_FOLDERS` and
`_NAMED_FOLDER_COMPONENTS` in `tools/file_writer.py`. It covers:

- Standard Windows shell folders: `Downloads`, `Documents`, `Desktop`,
  `Pictures`, `Videos`, `Music`, `Contacts`, `Favorites`, `Links`,
  `Searches`, `Saved Games`
- User top-level folders: `LocalMind`, `Dev`, `Scripts`, `docs`, `shared`,
  `workflows`, `examples`, `factory`, `config`, `data`, `OneDrive`

To add a new known folder, update both `_NAMED_FOLDERS` (canonical casing)
and `_NAMED_FOLDER_COMPONENTS` (lowercase lookup set). They must stay in sync.

External drives (`D:\`, `E:\`, network paths) are not supported yet. The plan
is an opt-in `LOCALMIND_EXTRA_PATHS` env var — see `05-decisions.md` ADR-004.

## Cache policy

**Setting:** `LOCALMIND_CACHE_MAX_AGE_DAYS` (default: `7`)

**Trigger:** Lazy — runs on every write, before the write happens.

**Scope:** Top-level entries in `~/LocalMind/` only. If a top-level directory
is expired, it is deleted recursively (all contents). A fresh top-level
directory is never recursed into — its contents are kept regardless of age.

**Protected entries** (never deleted):
- `localmind.db`
- `localmind.db-shm`
- `localmind.db-wal`
- `uploads/`

**Implementation:** `_cleanup_cache()` in `tools/file_writer.py`

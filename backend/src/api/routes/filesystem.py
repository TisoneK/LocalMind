"""
File system utility routes.

GET  /api/files            — list files in a directory (read-only, no side effects)
GET  /api/files/content    — read a file's text content for UI preview (docx/pdf/xlsx
                             parsed via tools.file_reader; images returned as a data URL)
GET  /api/files/meta       — metadata for a single file
POST /api/open-file        — open a file with the OS default application
POST /api/open-folder      — open a folder in the OS file manager (explicit action only)
POST /api/confirm-write    — confirm a pending permission-gated file write
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.agent.constants import FILE_READ_MAX_BYTES
from core.config import settings

router = APIRouter()

# Spreadsheets get a structured per-sheet table preview (tabs in the UI).
_SPREADSHEET_EXTS = {".xlsx", ".csv"}
# Binary formats the file_reader tool parses into plain text for preview.
_OFFICE_EXTS = {".pdf", ".docx"}
# Image formats returned as inline data URLs so the browser renders them directly.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}
# Plain-text / code extensions shown verbatim (everything else falls back to
# UTF-8 decode with the same cap the engine uses).
_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".env", ".sh", ".bash", ".rs", ".go", ".java",
    ".c", ".h", ".cpp", ".hpp", ".html", ".xml", ".css", ".sql", ".log",
}


class OpenFileRequest(BaseModel):
    path: str


class ConfirmWriteRequest(BaseModel):
    path: str
    content: str = ""
    # Structured per-sheet rows for spreadsheet writes (xlsx/csv). When present,
    # the write goes through write_spreadsheet instead of the plain-text _do_write.
    sheets: list[dict] | None = None


class FileListRequest(BaseModel):
    path: str = "."


@router.post("/open-file")
async def open_file(req: OpenFileRequest):
    """Open a file using the OS default application."""
    path = Path(req.path).resolve()

    # Safety: only open files within allowed paths
    if not settings.is_path_allowed(path):
        raise HTTPException(
            status_code=403,
            detail=f"Path is outside allowed folders: {path}",
        )

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        if sys.platform == "win32":
            # SECURITY: Avoid shell=True — "start" is a cmd.exe builtin, so
            # invoke cmd explicitly with the list form. This prevents shell
            # metacharacter injection via the path.
            subprocess.Popen(["cmd", "/c", "start", "", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return {"opened": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open file: {e}")


@router.post("/open-folder")
async def open_folder(req: OpenFileRequest):
    """Open a folder using the OS file manager."""
    path = Path(req.path).resolve()

    # Safety: only open folders within allowed paths
    if not settings.is_path_allowed(path):
        raise HTTPException(
            status_code=403,
            detail=f"Path is outside allowed folders: {path}",
        )

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found: {path}")

    try:
        if sys.platform == "win32":
            # explorer.exe opens the folder in File Explorer
            subprocess.Popen(["explorer", str(path)], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return {"opened": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {e}")


@router.get("/files")
async def list_files(path: str = ""):
    """List files and directories at the given path (read-only, no side effects).

    Defaults to the user's home directory (~) when no path is provided,
    NOT the server's CWD (which is backend/ in dev mode).
    """
    try:
        if not path or path == ".":
            path = os.path.expanduser("~")
        dir_path = Path(path).resolve()

        if not settings.is_path_allowed(dir_path):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")

        if not dir_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not dir_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        entries = []
        for entry in os.scandir(dir_path):
            try:
                stat = entry.stat()
                import datetime

                entries.append(
                    {
                        "name": entry.name,
                        "type": "folder" if entry.is_dir() else "file",
                        "path": entry.path,
                        "size": stat.st_size if entry.is_file() else 0,
                        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "extension": Path(entry.name).suffix.lower().lstrip(".")
                        if entry.is_file()
                        else "",
                        "is_symlink": entry.is_symlink(),
                    }
                )
            except PermissionError:
                continue

        entries.sort(key=lambda e: (e["type"] != "folder", e["name"].lower()))
        return {"children": entries}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {e}")


@router.get("/files/recent")
async def recent_files(path: str = "", limit: int = 10):
    """Most-recently-modified files under the given root (B-2026-08-23-16).

    Bounded recursive walk (skips hidden dirs and caps the scan), returning
    the `limit` newest files with size/modified metadata — powers the Files
    tab's "Recent files" section. Read-only.
    """
    import datetime

    try:
        if not path or path == ".":
            path = os.path.expanduser("~")
        root = Path(path).resolve()
        if not settings.is_path_allowed(root):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")
        if not root.exists() or not root.is_dir():
            raise HTTPException(status_code=404, detail="Path not found")

        limit = max(1, min(int(limit or 10), 100))
        # Bounded scan: never descend into hidden dirs (node_modules, .git, …)
        # and stop after visiting SCAN_CAP entries so a huge tree can't hang.
        _SCAN_CAP = 20_000
        _MAX_DEPTH = 8
        found: list[dict] = []
        visited = 0

        def _walk(d: Path, depth: int) -> None:
            nonlocal visited
            if depth > _MAX_DEPTH:
                return
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
            except OSError:
                return
            for entry in entries:
                if visited >= _SCAN_CAP:
                    return
                visited += 1
                name = entry.name
                if name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        _walk(Path(entry.path), depth + 1)
                    elif entry.is_file():
                        st = entry.stat()
                        found.append(
                            {
                                "name": name,
                                "type": "file",
                                "path": entry.path,
                                "relPath": os.path.relpath(entry.path, root),
                                "size": st.st_size,
                                "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                            }
                        )
                except OSError:
                    continue

        _walk(root, 0)
        found.sort(key=lambda f: f["modified"], reverse=True)
        return {"files": found[:limit]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list recent files: {e}")


@router.get("/files/search")
async def search_files(path: str = "", q: str = ""):
    """Recursively search for files/folders by name under the given path.

    Case-insensitive substring match on the entry name (not the full path),
    capped at 200 results so a huge tree can't flood the UI. Read-only.
    """
    try:
        if not path or path == ".":
            path = os.path.expanduser("~")
        root = Path(path).resolve()
        query = (q or "").strip().lower()
        if not query:
            return {"results": []}
        if not settings.is_path_allowed(root):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")
        if not root.exists() or not root.is_dir():
            raise HTTPException(status_code=404, detail="Path not found")

        import datetime

        results = []
        try:
            walker = os.walk(root)
            for dirpath, dirnames, filenames in walker:
                dirnames.sort()
                # Cap traversal: stop descending once we have enough results
                # (os.walk can't be pruned mid-iteration cheaply, but we can
                # avoid scanning further subtrees by checking the cap).
                for name in sorted(filenames):
                    if query in name.lower():
                        full = os.path.join(dirpath, name)
                        try:
                            st = os.stat(full)
                        except OSError:
                            continue
                        results.append(
                            {
                                "name": name,
                                "type": "file",
                                "path": full,
                                "relPath": os.path.relpath(full, root),
                                "size": st.st_size,
                                "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                            }
                        )
                        if len(results) >= 200:
                            break
                if len(results) >= 200:
                    break
                for name in dirnames:
                    if query in name.lower():
                        full = os.path.join(dirpath, name)
                        try:
                            st = os.stat(full)
                        except OSError:
                            continue
                        results.append(
                            {
                                "name": name,
                                "type": "folder",
                                "path": full,
                                "relPath": os.path.relpath(full, root),
                                "size": 0,
                                "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                            }
                        )
                        if len(results) >= 200:
                            break
                if len(results) >= 200:
                    break
        except PermissionError:
            pass
        results.sort(key=lambda e: (e["type"] != "folder", e["relPath"].lower()))
        return {"results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search: {e}")


@router.delete("/files")
async def delete_file(path: str):
    """Delete a file (or empty folder) the user explicitly chooses.

    Gated by the same allowed-folder check as listing: the path must resolve
    inside an allowed user folder. Folders are only removed when empty (a
    non-empty recursive delete is too destructive for a browser action).
    """
    try:
        if not path:
            raise HTTPException(status_code=400, detail="Path is required")
        target = Path(path).resolve()
        if not settings.is_path_allowed(target):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if target.is_dir():
            try:
                next(target.iterdir())
                raise HTTPException(status_code=400, detail="Folder is not empty")
            except StopIteration:
                target.rmdir()
        else:
            target.unlink()
        return {"deleted": str(target)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")


@router.get("/files/download")
async def download_file(path: str):
    """Stream a file's raw bytes as an attachment download."""
    try:
        if not path:
            raise HTTPException(status_code=400, detail="Path is required")
        target = Path(path).resolve()
        if not settings.is_path_allowed(target):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")
        if not target.exists() or target.is_dir():
            raise HTTPException(status_code=404, detail="Path not found")
        from fastapi.responses import FileResponse

        return FileResponse(
            target,
            filename=target.name,
            media_type="application/octet-stream",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download: {e}")


@router.get("/files/meta")
async def get_file_meta(path: str):
    """Get detailed metadata for a single file or directory."""
    try:
        file_path = Path(path).resolve()

        if not settings.is_path_allowed(file_path):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        stat = file_path.stat()
        import datetime

        return {
            "name": file_path.name,
            "path": str(file_path),
            "type": "folder" if file_path.is_dir() else "file",
            "size": stat.st_size,
            "size_human": _human_size(stat.st_size),
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "extension": file_path.suffix.lower().lstrip(".") if file_path.is_file() else "",
            "is_symlink": file_path.is_symlink(),
            "parent": str(file_path.parent),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get file metadata: {e}")


@router.get("/files/content")
async def get_file_content(path: str):
    """Read a file's text content for UI preview (read-only, no side effects).

    Text/code files are read verbatim (capped at FILE_READ_MAX_BYTES);
    docx/pdf/xlsx/csv are parsed into text via tools.file_reader.parse_file;
    images are returned as an inline data URL so the browser can render them
    directly without a binary-download round trip.
    """
    try:
        file_path = Path(path).resolve()

        if not settings.is_path_allowed(file_path):
            raise HTTPException(status_code=403, detail="Path is outside allowed folders")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        ext = file_path.suffix.lower()
        size = file_path.stat().st_size
        truncated = size > FILE_READ_MAX_BYTES

        # Images → inline data URL (no OCR — the browser is the renderer).
        if ext in _IMAGE_EXTS:
            data = file_path.read_bytes()[: FILE_READ_MAX_BYTES]
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".webp": "image/webp",
                ".tiff": "image/tiff",
            }.get(ext, "image/png")
            return {
                "path": str(file_path),
                "name": file_path.name,
                "extension": ext.lstrip("."),
                "size": size,
                "truncated": truncated,
                "editable": False,
                "image_data_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
            }

        # Spreadsheets → structured per-sheet rows so the UI can render real
        # tabs + a table instead of flat text.
        if ext in _SPREADSHEET_EXTS:
            from tools.file_reader import parse_spreadsheet

            data = file_path.read_bytes()[: FILE_READ_MAX_BYTES]
            sheets = await parse_spreadsheet(data, file_path.name)
            flat = "\n\n".join(
                f"=== {s['name']} ===\n" + "\n".join("\t".join(r) for r in s["rows"])
                for s in sheets
            )
            return {
                "path": str(file_path),
                "name": file_path.name,
                "extension": ext.lstrip("."),
                "size": size,
                "truncated": truncated,
                "editable": False,
                "sheets": sheets,
                "text": flat,
            }

        # Office/binary formats → reuse the engine's own parser so the preview
        # matches exactly what the agent sees.
        if ext in _OFFICE_EXTS or ext not in _TEXT_EXTS:
            from tools.file_reader import parse_file

            data = file_path.read_bytes()[: FILE_READ_MAX_BYTES]
            attachment = await parse_file(
                data,
                file_path.name,
                "application/octet-stream",
                chunk_size=FILE_READ_MAX_BYTES,  # no chunking for preview
            )
            return {
                "path": str(file_path),
                "name": file_path.name,
                "extension": ext.lstrip("."),
                "size": size,
                "truncated": truncated,
                # Parsed text is a lossy flattening of the binary format —
                # writing it back would destroy the document, so never editable.
                "editable": False,
                "text": "\n\n".join(attachment.chunks),
            }

        # Plain text / code → verbatim UTF-8 with the same cap.
        raw = file_path.read_bytes()[: FILE_READ_MAX_BYTES]
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to decode file: {e}")
        return {
            "path": str(file_path),
            "name": file_path.name,
            "extension": ext.lstrip("."),
            "size": size,
            "truncated": truncated,
            "editable": True,
            "text": text,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")


def _human_size(n: int) -> str:
    # Delegate to the shared helper in core.utils. Kept as a thin wrapper
    # so existing call sites in this module don't need updating.
    from core.utils import human_size

    return human_size(n)


@router.post("/confirm-write")
async def confirm_write(req: ConfirmWriteRequest):
    """Execute a previously permission-gated file write.

    Plain text/code files go through _do_write with `content`. Spreadsheet
    files (xlsx/csv) go through write_spreadsheet with the structured `sheets`
    payload the preview editor sends — writing a text blob over an xlsx would
    corrupt it.
    """
    from tools.file_writer import _do_write, write_spreadsheet

    path = Path(req.path).resolve()

    if not settings.is_path_allowed(path):
        raise HTTPException(status_code=403, detail="Path is outside allowed folders")

    if req.sheets is not None:
        try:
            result = await write_spreadsheet(path, req.sheets)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "path": result.metadata.get("path", ""),
            "filename": result.metadata.get("filename", ""),
            "bytes": result.metadata.get("bytes", 0),
            "mode": "spreadsheet",
            "content": result.content,
        }

    result = await _do_write(path, req.content)
    return {
        "path": result.metadata.get("path", ""),
        "filename": result.metadata.get("filename", ""),
        "bytes": result.metadata.get("bytes", 0),
        "mode": "text",
        "content": result.content,
    }

"""
File system utility routes.

GET  /api/files       — list files in a directory (read-only, no side effects)
POST /api/open-file   — open a file with the OS default application
POST /api/open-folder — open a folder in the OS file manager (explicit action only)
POST /api/confirm-write — confirm a pending permission-gated file write
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config import settings

router = APIRouter()


class OpenFileRequest(BaseModel):
    path: str


class ConfirmWriteRequest(BaseModel):
    path: str
    content: str


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
async def list_files(path: str = "."):
    """List files and directories at the given path (read-only, no side effects)."""
    try:
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
                entries.append({
                    "name": entry.name,
                    "type": "folder" if entry.is_dir() else "file",
                    "path": entry.path,
                    "size": stat.st_size if entry.is_file() else 0,
                })
            except PermissionError:
                continue

        entries.sort(key=lambda e: (e["type"] != "folder", e["name"].lower()))
        return {"children": entries}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {e}")


@router.post("/confirm-write")
async def confirm_write(req: ConfirmWriteRequest):
    """Execute a previously permission-gated file write."""
    from tools.file_writer import _do_write
    path = Path(req.path).resolve()

    if not settings.is_path_allowed(path):
        raise HTTPException(status_code=403, detail="Path is outside allowed folders")

    result = await _do_write(path, req.content)
    return {
        "path": result.metadata.get("path", ""),
        "filename": result.metadata.get("filename", ""),
        "bytes": result.metadata.get("bytes", 0),
        "content": result.content,
    }

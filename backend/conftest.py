"""
Backend-level conftest — ensures `src/` is on sys.path for test collection.

The pyproject.toml declares `pythonpath = ["src"]`, but some pytest versions
don't honor this setting reliably. This conftest is a belt-and-suspenders
fallback that inserts src/ at import time so test modules can do
`from tools.file_reader import ...` without a ModuleNotFoundError.
"""
import sys
from pathlib import Path

_src = str(Path(__file__).parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

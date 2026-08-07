"""Plugin package for Modular File Manager.

Host lives in ``modular-file-manager.py`` (hyphenated; not a normal import name).
Plugins load it via :func:`import_host`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_HOST_NAME = "modular_file_manager"
_HOST_FILE = "modular-file-manager.py"


def import_host() -> ModuleType:
    """Return the toolkit host module (BaseFileOperation, plugin_entry, …)."""
    existing = sys.modules.get(_HOST_NAME)
    if existing is not None and hasattr(existing, "BaseFileOperation"):
        return existing

    # Host already running as __main__ and registered under this name
    main = sys.modules.get("__main__")
    if (
        main is not None
        and hasattr(main, "BaseFileOperation")
        and hasattr(main, "plugin_entry")
    ):
        sys.modules.setdefault(_HOST_NAME, main)
        return main

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    path = root / _HOST_FILE
    if not path.is_file():
        raise ImportError(f"Toolkit host not found: {path}")

    spec = importlib.util.spec_from_file_location(_HOST_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load toolkit host from {path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[_HOST_NAME] = mod
    spec.loader.exec_module(mod)
    return mod

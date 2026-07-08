"""Shared loader for .scripts tool tests.

The custom sales tools live outside core/ and several share the filename
server.py, so they are loaded via importlib under distinct module names
instead of sys.path manipulation.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1].parent  # .scripts/


def load_tool_module(alias: str, relative_path: str):
    """Load a .scripts tool file as a module under a unique alias."""
    target = SCRIPTS_DIR / relative_path
    spec = importlib.util.spec_from_file_location(alias, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module

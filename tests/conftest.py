"""
Pytest fixtures and shared setup for Iftar Slot Checker tests.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# Load iftar-slot module by path (filename has hyphen)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "iftar-slot.py"


def load_iftar_module():
    """Load the iftar-slot script as a module for testing."""
    spec = importlib.util.spec_from_file_location("iftar_slot", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["iftar_slot"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def iftar_module():
    """Load the iftar-slot module once per test module."""
    return load_iftar_module()


@pytest.fixture(autouse=True)
def reset_module_state(iftar_module):
    """Reset global state before each test so tests are isolated."""
    iftar_module.last_notifications.clear()
    iftar_module.last_states.clear()
    iftar_module.consecutive_fetch_failures = 0
    iftar_module._first_run_after_load = True
    yield
    iftar_module.last_notifications.clear()
    iftar_module.last_states.clear()
    iftar_module.consecutive_fetch_failures = 0

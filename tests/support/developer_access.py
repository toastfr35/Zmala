"""Load privileged Linux helpers without platform fcntl on Windows."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).resolve().parents[2] / 'build_tools/linux' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'fcntl': SimpleNamespace()}):
        spec.loader.exec_module(result)
    return result

"""Load Linux helpers without executing their entrypoints or native OS actions."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location('unit_'+name.replace('-', '_'), ROOT/'build_tools/linux'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    substitutes = {} if sys.platform.startswith('linux') else {'fcntl': Mock(LOCK_EX=2, LOCK_NB=4)}
    with patch.dict(sys.modules, substitutes):
        spec.loader.exec_module(module)
    return module


def shell(script, directory=None):
    executable = 'C:/msys64/usr/bin/bash.exe' if sys.platform == 'win32' else shutil.which('sh')
    if not executable or not Path(executable).exists():
        raise RuntimeError('POSIX shell required for installer unit checks (MSYS2 Bash on Windows)')
    return subprocess.run([executable, '-s'], input=script, text=True, capture_output=True,
                          cwd=directory, timeout=20)

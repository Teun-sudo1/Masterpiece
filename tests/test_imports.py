"""Every module of the app compiles and imports, also the ones the other tests never load
(tray, window): a mistake there makes the installed app fall back to the browser."""

from __future__ import annotations

import importlib
import pkgutil
import py_compile
from pathlib import Path

import pytest

import masterpiece

PKG = Path(masterpiece.__file__).parent
FILES = sorted(PKG.rglob("*.py"))


@pytest.mark.parametrize("path", FILES, ids=[str(p.relative_to(PKG)) for p in FILES])
def test_every_file_compiles(path):
    py_compile.compile(str(path), doraise=True)


def test_every_module_imports():
    names = [m.name for m in pkgutil.walk_packages([str(PKG)], "masterpiece.")]
    assert "masterpiece.tray" in names and "masterpiece.window" in names
    for name in names:
        if name == "masterpiece.__main__":
            continue
        importlib.import_module(name)

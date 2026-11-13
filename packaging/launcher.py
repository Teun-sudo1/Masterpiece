"""Entry point for Masterpiece.exe (PyInstaller can't start a package with -m)."""

import sys

from masterpiece.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

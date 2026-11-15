#!/usr/bin/env python3
"""rlab launcher: research lab CLI (forge / lab / crew / retro)."""
import pathlib
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from rlab_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

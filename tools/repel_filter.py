#!/usr/bin/env python3
"""Launcher for the portable calculator in tools/repel_calc/."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "repel_calc" / "repel_filter.py"

if __name__ == "__main__":
    sys.argv[0] = str(TARGET)
    runpy.run_path(str(TARGET), run_name="__main__")

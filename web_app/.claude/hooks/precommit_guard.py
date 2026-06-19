# -*- coding: utf-8 -*-
"""Stub hook for web_app cwd — delegates to project-root precommit_guard."""
import os
import sys
import runpy

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL = os.path.join(PROJECT_ROOT, "..", ".claude", "hooks", "precommit_guard.py")
REAL = os.path.normpath(REAL)
if os.path.exists(REAL):
    runpy.run_path(REAL, run_name="__main__")
else:
    sys.exit(0)

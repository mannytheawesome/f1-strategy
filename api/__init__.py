"""F1 Strategy Predictor API package.

Ensures the repo root is importable (so `data.*` and `engine.*` resolve)
regardless of how the app is launched — this runs before any submodule.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

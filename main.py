"""Isolated Python distribution entry; add only this package's source/dependencies."""
from pathlib import Path
import sys
root = Path(__file__).resolve().parent
sys.path[:0] = [str(root), str(root / 'packages')]
from lazybuddy_hongguo.__main__ import main
main()

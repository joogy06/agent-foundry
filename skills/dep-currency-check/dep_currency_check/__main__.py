"""Entry point so `python3 -m dep_currency_check ...` works.

NOTE: the actual module package name is `dep_currency_check` (set via the
PYTHONPATH/runtime install path), NOT `scripts`. Tests use a path-mangle so
that `dep_currency_check` resolves to this directory. See tests/__init__.py.
"""
import sys
from .dep_currency_check import main

if __name__ == "__main__":
    sys.exit(main())

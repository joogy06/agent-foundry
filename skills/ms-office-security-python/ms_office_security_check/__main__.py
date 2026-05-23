"""Entry point so `python3 -m ms_office_security_check ...` works.

Mirrors dep-currency-check's __main__ shape.
"""
import sys
from .ms_office_security_check import main

if __name__ == "__main__":
    sys.exit(main())

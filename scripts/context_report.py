"""Print what the coach's chat context costs for a mode. See strides_ai/context_report.py.

Usage: .venv/bin/python scripts/context_report.py --mode hybrid
"""

import sys

from strides_ai.context_report import main

if __name__ == "__main__":
    sys.exit(main())

"""Replay a fixed set of coach questions against a copy of the database. See
strides_ai/replay_chat.py. This calls a real provider (it costs money), so it only does so with
--confirm-cost; the real database is never touched.

Usage: .venv/bin/python scripts/replay_chat.py            # list the prompts
       .venv/bin/python scripts/replay_chat.py --confirm-cost --provider claude
"""

import sys

from strides_ai.replay_chat import main

if __name__ == "__main__":
    sys.exit(main())

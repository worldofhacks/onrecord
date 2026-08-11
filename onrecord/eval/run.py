"""`make eval` entrypoint — runs the IR-metrics scoreboard.

Wired up by T-005. Tonight this is a signature-only stub: it exits non-zero
with a clear message rather than silently doing nothing.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write("onrecord.eval.run: not implemented\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""`onrecord` CLI — `search` and `demo` subcommands (design spec Sec 3/7).

Wired up by T-010. Tonight this is a signature-only stub: it exits non-zero
with a clear message rather than silently doing nothing.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "<none>"
    print(f"onrecord.cli: not implemented (command: {cmd})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

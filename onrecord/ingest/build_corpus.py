"""`make ingest` entrypoint — runs the registry-driven corpus adapters.

Wired up by Wave-2/3 tickets (T-006/T-007/T-008/T-010). Tonight this is a
signature-only stub: it exits non-zero with a clear message rather than
silently doing nothing.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write("onrecord.ingest.build_corpus: not implemented\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/bin/bash
# Every AC-n in the ticket file must appear as spec(T-xxx:AC-n) in tests/.
# Usage: .tdd-swarm/spec-lint.sh tickets/T-001.md
set -e
ticket_file="$1"
tid=$(basename "$ticket_file" .md)
fail=0
for ac in $(grep -oE '\*\*AC-[0-9]+\*\*' "$ticket_file" | grep -oE 'AC-[0-9]+' | sort -u); do
  if ! grep -rqE "spec\($tid:$ac\)" tests/ 2>/dev/null; then
    echo "MISSING: no test tagged spec($tid:$ac)"; fail=1
  fi
done
[ $fail -eq 0 ] && echo "spec-lint OK: all ACs covered for $tid"
exit $fail

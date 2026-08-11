#!/usr/bin/env python3
"""Export the Claude Code Pre-Search session transcript to a readable markdown doc.

Extracts user messages, assistant prose, and the AskUserQuestion decision
interview (questions + chosen answers) from the raw session JSONL. Tool
internals, file dumps, and system reminders are skipped.

Re-run before final submission to capture the latest state:
    python3 scripts/export_presearch_transcript.py
"""

import json
import re
import sys
from pathlib import Path

SESSION = Path.home() / (
    ".claude/projects/-Users-quietguy-Documents-Dev-Gauntlet-advanced-rag/"
    "d39a854e-2505-46d3-b460-9396d5100c96.jsonl"
)
OUT = Path(__file__).resolve().parent.parent / "docs" / "presearch-transcript.md"

SKIP_MARKERS = ("<system-reminder>", "<local-command-caveat>", "<command-name>")


def clean(text: str) -> str:
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    return text.strip()


def main() -> None:
    if not SESSION.exists():
        sys.exit(f"session file not found: {SESSION}")

    lines: list[str] = [
        "# Pre-Search AI Conversation — Reference Document",
        "",
        "Raw session: Claude Code (Opus), RelevanceEngine Assignment 02.",
        "Exported by `scripts/export_presearch_transcript.py`.",
        "",
    ]
    for raw in SESSION.read_text().splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") or {}
        role, content = msg.get("role"), msg.get("content")
        if not role or content is None:
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        for b in blocks:
            btype = b.get("type") if isinstance(b, dict) else None
            if btype == "text":
                text = clean(b.get("text", ""))
                if not text or any(m in text for m in SKIP_MARKERS):
                    continue
                header = "## 🧑 User" if role == "user" else "## 🤖 Assistant"
                lines += [header, "", text, ""]
            elif btype == "tool_use" and b.get("name") == "AskUserQuestion":
                for q in (b.get("input") or {}).get("questions", []):
                    lines += ["> **Decision point:** " + q.get("question", ""), ""]
                    for opt in q.get("options", []):
                        lines += [f"> - {opt.get('label', '')}"]
                    lines += [""]
            elif btype == "tool_result":
                text = ""
                rc = b.get("content")
                if isinstance(rc, str):
                    text = rc
                elif isinstance(rc, list):
                    text = " ".join(x.get("text", "") for x in rc if isinstance(x, dict))
                if "The user answered" in text:
                    lines += ["> **User's answer:** " + clean(text), ""]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

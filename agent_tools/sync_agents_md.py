#!/usr/bin/env python3
"""Regenerate the material workflow part of AGENTS.md from the skill body.

AGENTS.md = its own header (everything before "## Making a material from a description") + the body of
.claude/skills/material-maker/SKILL.md (after the front matter) with every heading one level deeper and the
title replaced. Run after editing SKILL.md: python3 agent_tools/sync_agents_md.py [--check]"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude/skills/material-maker/SKILL.md"
AGENTS = REPO / "AGENTS.md"
TITLE = "## Making a material from a description"


def build():
    skill = SKILL.read_text()
    body = skill[skill.index("\n# ") + 1:]
    body = re.sub(r"^(#+) ", r"#\1 ", body, flags=re.M)
    body = TITLE + body[body.index("\n"):]
    agents = AGENTS.read_text()
    return agents[:agents.index(TITLE)] + body


def main():
    new = build()
    if "--check" in sys.argv[1:]:
        ok = new == AGENTS.read_text()
        print("AGENTS.md in sync" if ok else "AGENTS.md out of sync with SKILL.md (run without --check)")
        return 0 if ok else 1
    AGENTS.write_text(new)
    print("AGENTS.md regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Mirror the live Hermes skill folder into this repository (skill -> repo, one way).

Usage: sync_from_skill.py SKILL_DIR [REPO_DIR]
Domain-specific reference packs and caches are excluded on purpose (see README).
"""
import os, shutil, sys

EXCLUDE_FILES = {
    "references/person-profile-research.md", "references/personality-frameworks.md",
    "references/codebook-iteration-lessons.md", "references/external-stt.md",
    "references/local-asr-farm.md",
}
EXCLUDE_DIRS = {"__pycache__", ".git"}
MIRRORED_TOP = ("SKILL.md", "assets", "references", "scripts", "templates")


def main():
    src = os.path.abspath(sys.argv[1])
    dst = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.getcwd())
    for top in MIRRORED_TOP:
        shutil.rmtree(os.path.join(dst, top), ignore_errors=True)
    n = 0
    for top in MIRRORED_TOP:
        p = os.path.join(src, top)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, top)); n += 1
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), src).replace(os.sep, "/")
                if rel in EXCLUDE_FILES or f.endswith(".pyc"):
                    continue
                out = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(os.path.join(root, f), out); n += 1
    print(f"mirrored {n} files from {src}")


if __name__ == "__main__":
    main()

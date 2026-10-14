#!/usr/bin/env python3
"""Raises a library file's version by one and sets its date, then validates.

Usage: python3 scripts/publish.py <tiles|projectors|both>
Prints "tiles now version 7" per file. Pair it with merge.py --no-bump: merge as many entries as a version
should carry, then publish once.
"""
import datetime, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

def bump(kind):
    path = os.path.join(ROOT, f"{kind}.json")
    data = json.load(open(path))
    data["version"] = int(data["version"]) + 1
    data["updated"] = datetime.date.today().isoformat()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return data["version"]

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("tiles", "projectors", "both"):
        fail("usage: publish.py <tiles|projectors|both>")
    kinds = ["tiles", "projectors"] if sys.argv[1] == "both" else [sys.argv[1]]
    versions = {kind: bump(kind) for kind in kinds}
    result = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "validate.py")], capture_output=True, text=True)
    if result.returncode != 0:
        fail("validate.py failed after the bump:\n" + result.stderr)
    for kind, version in versions.items():
        print(f"{kind} now version {version}")

if __name__ == "__main__":
    main()

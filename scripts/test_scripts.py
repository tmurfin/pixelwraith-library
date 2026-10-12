#!/usr/bin/env python3
"""Fixture issues through merge.py and validate.py, in a temporary copy of the repository files."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
fails = 0

def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        fails += 1

def run(args, stdin=None, cwd=None):
    return subprocess.run([sys.executable] + args, input=stdin, capture_output=True, text=True, cwd=cwd)

with tempfile.TemporaryDirectory() as tmp:
    for name in ("tiles.json", "projectors.json"):
        shutil.copy(os.path.join(ROOT, name), tmp)
    shutil.copytree(HERE, os.path.join(tmp, "scripts"))
    merge = [os.path.join(tmp, "scripts", "merge.py")]
    validate = [os.path.join(tmp, "scripts", "validate.py")]

    check(run(validate, cwd=tmp).returncode == 0, "the shipped files validate")

    issue = """Spec sheet: https://example.com/udx

Nice projector.

```json
{
  "manufacturer": "Barco",
  "model": "UDX-4K32",
  "resolution": {"width": 3840, "height": 2400},
  "lumens": 31000,
  "lenses": [{"name": "FLD+ 1.5-2.2", "throwMin": 2.2, "throwMax": 1.5}, {"name": "FLD+ 0.37", "throwMin": 0.37, "throwMax": null}]
}
```
"""
    before = json.load(open(os.path.join(tmp, "projectors.json")))
    result = run(merge + ["projectors"], stdin=issue, cwd=tmp)
    after = json.load(open(os.path.join(tmp, "projectors.json")))
    check(result.returncode == 0, "merge: a projector issue merges (" + result.stderr.strip() + ")")
    check(after["version"] == before["version"] + 1 and len(after["entries"]) == 1, "merge: version bumped, entry appended")
    entry = after["entries"][0]
    check(entry["id"] == "barco-udx-4k32" and entry["lenses"][0]["throwMin"] == 1.5 and entry["lenses"][0]["throwMax"] == 2.2, "merge: slug assigned, backwards zoom ordered")
    check("source" not in entry and len(after["updated"]) == 10, "merge: no source key, updated set")
    again = run(merge + ["projectors"], stdin=issue, cwd=tmp)
    check(again.returncode != 0 and "already" in again.stderr, "merge: the same projector again is refused")

    bad = issue.replace('"lumens": 31000', '"lumens": -4').replace("UDX-4K32", "UDX-4K40")
    check(run(merge + ["projectors"], stdin=bad, cwd=tmp).returncode != 0, "merge: negative lumens refused")
    dup = issue.replace("FLD+ 0.37", "FLD+ 1.5-2.2").replace("UDX-4K32", "UDX-4K40")
    check(run(merge + ["projectors"], stdin=dup, cwd=tmp).returncode != 0, "merge: duplicate lens names refused")

    tile_issue = """```json
{"manufacturer": "ROE", "model": "Carbon CB5", "tileResolution": {"width": 104, "height": 104}, "tileSize": {"width": 600, "height": 600}, "transparency": null}
```"""
    result = run(merge + ["tiles"], stdin=tile_issue, cwd=tmp)
    tiles = json.load(open(os.path.join(tmp, "tiles.json")))
    check(result.returncode == 0 and tiles["entries"][-1]["id"] == "roe-carbon-cb5", "merge: a tile issue merges with its slug")
    check(run(validate, cwd=tmp).returncode == 0, "the merged files validate")

    broken = json.load(open(os.path.join(tmp, "tiles.json")))
    broken["entries"][0]["tileSize"]["width"] = 0
    json.dump(broken, open(os.path.join(tmp, "tiles.json"), "w"))
    check(run(validate, cwd=tmp).returncode != 0, "validate: a zero size fails")

print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(0 if fails == 0 else 1)

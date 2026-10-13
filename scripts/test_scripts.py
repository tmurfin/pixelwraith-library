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
    # The fixtures run against small files of their own, so the live tiles.json and projectors.json can grow
    # without changing what the tests expect; the live files are only validated
    json.dump({"version": 1, "updated": "2026-10-12", "entries": [
        {"id": "absen-a3-pro", "manufacturer": "Absen", "model": "A3 Pro", "tileResolution": {"width": 128, "height": 128},
         "tileSize": {"width": 500, "height": 500}, "transparency": None}]}, open(os.path.join(tmp, "tiles.json"), "w"))
    json.dump({"version": 1, "updated": "2026-10-12", "entries": []}, open(os.path.join(tmp, "projectors.json"), "w"))
    shutil.copytree(HERE, os.path.join(tmp, "scripts"))
    merge = [os.path.join(tmp, "scripts", "merge.py")]
    validate = [os.path.join(tmp, "scripts", "validate.py")]

    check(run([os.path.join(HERE, "validate.py")], cwd=ROOT).returncode == 0, "the shipped files validate")

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
    check(after["version"] == before["version"] + 1 and len(after["entries"]) == len(before["entries"]) + 1, "merge: version bumped, entry appended")
    entry = after["entries"][-1]
    check(entry["id"] == "barco-udx-4k32" and entry["lenses"][0]["throwMin"] == 1.5 and entry["lenses"][0]["throwMax"] == 2.2, "merge: slug assigned, backwards zoom ordered")
    check("source" not in entry and len(after["updated"]) == 10, "merge: no source key, updated set")
    again = run(merge + ["projectors"], stdin=issue, cwd=tmp)
    check(again.returncode != 0 and "already" in again.stderr, "merge: the same projector again is refused")

    bad = issue.replace('"lumens": 31000', '"lumens": -4').replace("UDX-4K32", "UDX-4K40")
    check(run(merge + ["projectors"], stdin=bad, cwd=tmp).returncode != 0, "merge: negative lumens refused")
    dup = issue.replace("FLD+ 0.37", "FLD+ 1.5-2.2").replace("UDX-4K32", "UDX-4K40")
    check(run(merge + ["projectors"], stdin=dup, cwd=tmp).returncode != 0, "merge: duplicate lens names refused")

    old = issue.replace("UDX-4K32", "HDX-W12").replace('"lumens": 31000', '"lumens": 12000, "discontinued": true').replace('"throwMax": null}', '"throwMax": null, "discontinued": true}')
    result = run(merge + ["projectors"], stdin=old, cwd=tmp)
    entry = json.load(open(os.path.join(tmp, "projectors.json")))["entries"][-1]
    check(result.returncode == 0 and entry.get("discontinued") is True and entry["lenses"][1].get("discontinued") is True and "discontinued" not in entry["lenses"][0], "merge: discontinued flags carried on the projector and its lens, absent where not given")
    check(run(validate, cwd=tmp).returncode == 0, "validate: discontinued flags pass")
    word = old.replace('"discontinued": true,', '"discontinued": "yes",', 1).replace("HDX-W12", "HDX-W14")
    check(run(merge + ["projectors"], stdin=word, cwd=tmp).returncode != 0, "merge: a discontinued flag that is not true or false is refused")
    flagged = json.load(open(os.path.join(tmp, "projectors.json")))
    flagged["entries"][-1]["lenses"][0]["discontinued"] = 1
    json.dump(flagged, open(os.path.join(tmp, "projectors.json"), "w"))
    check(run(validate, cwd=tmp).returncode != 0, "validate: a discontinued flag that is not true or false fails")
    flagged["entries"][-1]["lenses"][0].pop("discontinued")
    json.dump(flagged, open(os.path.join(tmp, "projectors.json"), "w"))

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
    broken["entries"][0]["tileSize"]["width"] = True
    json.dump(broken, open(os.path.join(tmp, "tiles.json"), "w"))
    check(run(validate, cwd=tmp).returncode != 0, "validate: a boolean where a number belongs fails")
    bool_issue = tile_issue.replace('"width": 104', '"width": true').replace("Carbon CB5", "Carbon CB8")
    check(run(merge + ["tiles"], stdin=bool_issue, cwd=tmp).returncode != 0, "merge: a boolean where a number belongs is refused")

print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(0 if fails == 0 else 1)

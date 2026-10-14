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


    # --- no-bump merge, publish, and the approve-then-publish driver against a fake gh and git ---
    repaired = json.load(open(os.path.join(tmp, "tiles.json")))   # the validator checks above left entry 0 broken on purpose
    repaired["entries"][0]["tileSize"]["width"] = 500
    json.dump(repaired, open(os.path.join(tmp, "tiles.json"), "w"))
    before = json.load(open(os.path.join(tmp, "tiles.json")))
    staged = tile_issue.replace("Carbon CB5", "Carbon CB3")
    r = run(merge + ["tiles", "--no-bump"], stdin=staged, cwd=tmp)
    after = json.load(open(os.path.join(tmp, "tiles.json")))
    check(r.returncode == 0 and "(unpublished)" in r.stdout, "merge --no-bump: merges and says unpublished (" + r.stderr.strip() + ")")
    check(after["version"] == before["version"] and after["updated"] == before["updated"] and len(after["entries"]) == len(before["entries"]) + 1, "merge --no-bump: entry appended, version and date untouched")
    publish = [os.path.join(tmp, "scripts", "publish.py")]
    r = run(publish + ["tiles"], cwd=tmp)
    bumped = json.load(open(os.path.join(tmp, "tiles.json")))
    check(r.returncode == 0 and r.stdout.strip() == f"tiles now version {before['version'] + 1}" and bumped["version"] == before["version"] + 1 and len(bumped["updated"]) == 10, "publish: tiles bumped once and dated (" + r.stdout.strip() + ")")
    pj_before = json.load(open(os.path.join(tmp, "projectors.json")))["version"]
    r = run(publish + ["both"], cwd=tmp)
    check(r.returncode == 0 and json.load(open(os.path.join(tmp, "tiles.json")))["version"] == before["version"] + 2 and json.load(open(os.path.join(tmp, "projectors.json")))["version"] == pj_before + 1, "publish: both bumps both")
    check(run(publish + ["lenses"], cwd=tmp).returncode != 0, "publish: an unknown kind is refused")

    # The fake gh: answers from issues.json and keeps it current, logs every call; the fake git: logs every call
    fake_dir = os.path.join(tmp, "fake"); os.makedirs(fake_dir)
    gh_log = os.path.join(fake_dir, "gh.log"); git_log = os.path.join(fake_dir, "git.log")
    fake_gh = os.path.join(fake_dir, "gh")
    FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
open(os.path.join(here, "gh.log"), "a").write(" ".join(args) + "\\n")
path = os.path.join(here, "issues.json")
issues = json.load(open(path))
if args[:2] == ["label", "list"]:
    print(json.dumps(json.load(open(os.path.join(here, "labels.json"))))); sys.exit(0)
if args[:2] == ["issue", "list"]:
    label = args[args.index("--label") + 1]
    print(json.dumps([i for i in issues if label in i["labels"] and not i.get("closed")])); sys.exit(0)
if args[:2] == ["issue", "edit"]:
    issue = next(i for i in issues if str(i["number"]) == args[2])
    if "--add-label" in args: issue["labels"].append(args[args.index("--add-label") + 1])
    if "--remove-label" in args:
        name = args[args.index("--remove-label") + 1]
        issue["labels"] = [l for l in issue["labels"] if l != name]
if args[:2] == ["issue", "close"]:
    next(i for i in issues if str(i["number"]) == args[2])["closed"] = True
json.dump(issues, open(path, "w"))
"""
    open(fake_gh, "w").write(FAKE_GH)
    os.chmod(fake_gh, 0o755)
    fake_git = os.path.join(fake_dir, "git")
    with open(fake_git, "w") as f:   # logs every call but the driver's pre-flight status check
        f.write("#!/bin/sh\nif [ \"$1\" != status ]; then echo \"$@\" >> \"$(dirname \"$0\")/git.log\"; fi\n")
    os.chmod(fake_git, 0o755)
    driver = [os.path.join(tmp, "scripts", "publish_approved.py"), "--gh", fake_gh, "--git", fake_git]
    def body_for(maker, model, pitch_width=104):
        return tile_issue.replace("ROE", maker).replace("Carbon CB5", model).replace('"width": 104', f'"width": {pitch_width}')
    def reset_logs():
        open(gh_log, "w").close(); open(git_log, "w").close()
    def gh_calls():
        return [line.strip() for line in open(gh_log) if line.strip()]

    json.dump([{"name": "submission"}, {"name": "tile"}], open(os.path.join(fake_dir, "labels.json"), "w"))
    json.dump([], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    r = run(driver, cwd=tmp)
    check(r.returncode != 0 and "approved" in r.stderr and "merged" in r.stderr and open(git_log).read() == "", "driver: without the labels it stops before touching anything")

    json.dump([{"name": "submission"}, {"name": "tile"}, {"name": "approved"}, {"name": "merged"}], open(os.path.join(fake_dir, "labels.json"), "w"))
    json.dump([], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    tiles_v = json.load(open(os.path.join(tmp, "tiles.json")))["version"]
    r = run(driver, cwd=tmp)
    check(r.returncode == 0 and "nothing to publish" in r.stdout and open(git_log).read() == "" and json.load(open(os.path.join(tmp, "tiles.json")))["version"] == tiles_v, "driver: nothing approved → nothing to publish, no commit, no bump")

    # Three approved issues: two tiles (one a duplicate of CB3 merged above), one projector; one with a bad title
    issues = [
        {"number": 31, "title": "Tile: Absen PL2.5", "body": body_for("Absen", "PL2.5"), "labels": ["submission", "tile", "approved"]},
        {"number": 32, "title": "Tile: ROE Carbon CB3", "body": body_for("ROE", "Carbon CB3"), "labels": ["submission", "tile", "approved"]},
        {"number": 33, "title": "Projector: Barco UDM-4K22", "body": issue.replace("UDX-4K32", "UDM-4K22"), "labels": ["submission", "projector", "approved"]},
        {"number": 34, "title": "Something else", "body": "no json", "labels": ["approved"]},
        {"number": 35, "title": "Tile: Not approved", "body": body_for("X", "Y"), "labels": ["submission", "tile"]},
    ]
    json.dump(issues, open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    tiles_v = json.load(open(os.path.join(tmp, "tiles.json")))["version"]; pj_v = json.load(open(os.path.join(tmp, "projectors.json")))["version"]
    r = run(driver, cwd=tmp)
    calls = gh_calls()
    tiles_now = json.load(open(os.path.join(tmp, "tiles.json"))); pj_now = json.load(open(os.path.join(tmp, "projectors.json")))
    check(r.returncode == 0, "driver: a run with refusals still succeeds (" + r.stderr.strip() + ")")
    check(any(e["id"] == "absen-pl2-5" for e in tiles_now["entries"]) and any(e["id"] == "barco-udm-4k22" for e in pj_now["entries"]), "driver: the approved tile and projector are in the files")
    check(tiles_now["version"] == tiles_v + 1 and pj_now["version"] == pj_v + 1, "driver: each changed file bumped once")
    check("issue edit 31 --add-label merged --remove-label approved" in calls and "issue edit 33 --add-label merged --remove-label approved" in calls, "driver: merged issues labelled merged, un-approved")
    check(any(c.startswith("issue comment 32 --body Could not merge:") and "already" in c for c in calls) and "issue edit 32 --remove-label approved" in calls, "driver: a duplicate is commented and un-approved, the rest publish")
    check(any(c.startswith("issue comment 34 --body Could not tell whether this is a tile or a projector") for c in calls) and "issue edit 34 --remove-label approved" in calls, "driver: a bad title is commented and un-approved")
    check(not any(" 35 " in c for c in calls), "driver: an issue without approved is untouched")
    git_calls = [line.strip() for line in open(git_log) if line.strip()]
    check(git_calls[-2].startswith("commit -m Publish tiles version ") and f"tiles version {tiles_v + 1}, projectors version {pj_v + 1}" in git_calls[-2] and git_calls[-1] == "push", "driver: one commit naming both versions, then push (" + " | ".join(git_calls) + ")")
    check(f"issue close 31 --comment Added in version {tiles_v + 1}" in calls and f"issue close 33 --comment Added in version {pj_v + 1}" in calls and "issue edit 31 --remove-label merged" in calls, "driver: closed with each kind's version and un-merged")
    check(calls.index("issue edit 31 --add-label merged --remove-label approved") < [i for i, c in enumerate(calls) if c.startswith("issue close 31")][0], "driver: merged before closed")

    # A merged issue from an earlier run: closed when its entry is in the file, sent back when not
    json.dump([
        {"number": 36, "title": "Tile: Absen PL2.5", "body": body_for("Absen", "PL2.5"), "labels": ["submission", "tile", "merged"]},
        {"number": 37, "title": "Tile: Gone Model", "body": body_for("Gone", "Model"), "labels": ["submission", "tile", "merged"]},
        {"number": 38, "title": "Tile: Absen PL3.9", "body": body_for("Absen", "PL3.9"), "labels": ["submission", "tile", "approved"]},
    ], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    tiles_v = json.load(open(os.path.join(tmp, "tiles.json")))["version"]
    r = run(driver, cwd=tmp)
    calls = gh_calls()
    check(r.returncode == 0 and f"issue close 36 --comment Added in version {tiles_v + 1}" in calls and "issue edit 36 --remove-label merged" in calls, "driver: a merged issue from an earlier run is closed with the new version when its entry is in the file")
    check(any(c.startswith("issue comment 37 --body Merged entry not found") for c in calls) and "issue edit 37 --remove-label merged" in calls and not any(c.startswith("issue close 37") for c in calls), "driver: a merged issue whose entry is missing is sent back, not closed")
    check(f"issue close 38 --comment Added in version {tiles_v + 1}" in calls, "driver: this run's approved issue closed too")

    # Only merged, nothing approved: no bump, no commit, the stray merged issue sent back
    json.dump([{"number": 39, "title": "Tile: Gone Again", "body": body_for("Gone", "Again"), "labels": ["merged"]}], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    tiles_v = json.load(open(os.path.join(tmp, "tiles.json")))["version"]
    r = run(driver, cwd=tmp)
    check(r.returncode == 0 and json.load(open(os.path.join(tmp, "tiles.json")))["version"] == tiles_v and open(git_log).read() == "" and any(c.startswith("issue comment 39 --body Merged entry not found") for c in gh_calls()), "driver: nothing approved → no publish, a stray merged issue is still sent back")


    # --- review fixes: a bad entry never leaves the file changed; NaN is refused; the driver guards its run ---
    snapshot = open(os.path.join(tmp, "tiles.json")).read()
    empty_slug = tile_issue.replace("ROE", "株式会社").replace("Carbon CB5", "製品")
    r = run(merge + ["tiles", "--no-bump"], stdin=empty_slug, cwd=tmp)
    check(r.returncode != 0 and "letter or digit" in r.stderr and open(os.path.join(tmp, "tiles.json")).read() == snapshot, "merge: a name without a letter or digit is refused and the file is untouched")
    nan_issue = issue.replace('"lumens": 31000', '"lumens": NaN').replace("UDX-4K32", "UDX-NAN")
    r = run(merge + ["projectors"], stdin=nan_issue, cwd=tmp)
    check(r.returncode != 0 and "not a number" in r.stderr, "merge: NaN is refused")
    inf_issue = issue.replace('"throwMin": 0.37', '"throwMin": 1e400').replace("UDX-4K32", "UDX-INF")
    check(run(merge + ["projectors"], stdin=inf_issue, cwd=tmp).returncode != 0, "merge: an infinite number is refused")
    pj_path = os.path.join(tmp, "projectors.json")
    pj_good = open(pj_path).read()
    open(pj_path, "w").write(pj_good.replace('"lumens": 31000', '"lumens": NaN', 1))
    check(run(validate, cwd=tmp).returncode != 0, "validate: NaN in a file fails")
    open(pj_path, "w").write(pj_good)

    dirty_git = os.path.join(fake_dir, "git-dirty")
    open(dirty_git, "w").write("#!/bin/sh\nif [ \"$1\" = status ]; then echo ' M tiles.json'; fi\n")
    os.chmod(dirty_git, 0o755)
    json.dump([{"number": 40, "title": "Tile: Absen PL5", "body": body_for("Absen", "PL5"), "labels": ["approved"]}], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    snapshot = open(os.path.join(tmp, "tiles.json")).read()
    r = run([driver[0], "--gh", fake_gh, "--git", dirty_git], cwd=tmp)
    check(r.returncode != 0 and "uncommitted" in r.stderr and open(os.path.join(tmp, "tiles.json")).read() == snapshot and open(gh_log).read() == "", "driver: a dirty library file stops the run before anything")

    json.dump([{"number": 41, "title": "Tile: ROE Carbon CB3", "body": body_for("ROE", "Carbon CB3"), "labels": ["merged"]}], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    tiles_v = json.load(open(os.path.join(tmp, "tiles.json")))["version"]
    r = run(driver, cwd=tmp)
    check(r.returncode == 0 and f"issue close 41 --comment Added in version {tiles_v}" in gh_calls() and open(git_log).read() == "", "driver: a merged leftover already in the file is closed with the current version, no commit")

    pushfail_git = os.path.join(fake_dir, "git-pushfail")
    open(pushfail_git, "w").write("#!/bin/sh\nif [ \"$1\" != status ]; then echo \"$@\" >> \"$(dirname \"$0\")/git.log\"; fi\nif [ \"$1\" = push ]; then echo 'rejected' >&2; exit 1; fi\n")
    os.chmod(pushfail_git, 0o755)
    json.dump([{"number": 42, "title": "Tile: Absen PL6", "body": body_for("Absen", "PL6"), "labels": ["approved"]}], open(os.path.join(fake_dir, "issues.json"), "w"))
    reset_logs()
    r = run([driver[0], "--gh", fake_gh, "--git", pushfail_git], cwd=tmp)
    issues_after = json.load(open(os.path.join(fake_dir, "issues.json")))
    check(r.returncode != 0 and "push" in r.stderr and not any(c.startswith("issue close") for c in gh_calls()) and "merged" in issues_after[0]["labels"], "driver: a failed push exits non-zero, closes nothing, the issue keeps merged")
    check("Traceback" not in r.stderr, "driver: a git failure is a message, not a traceback")
print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(0 if fails == 0 else 1)

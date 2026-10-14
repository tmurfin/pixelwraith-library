#!/usr/bin/env python3
"""Merges every open issue labelled `approved`, bumps each changed file's version once, commits to main, pushes,
and closes the issues with the version they went out in. The Publish workflow runs this; it runs by hand too.

Usage: python3 scripts/publish_approved.py [--gh PATH] [--git PATH]
Talks to GitHub only through the gh CLI (GH_TOKEN or a login) and to the repository through git, both
replaceable for tests. A refused issue (bad title, duplicate entry, bad numbers) is commented and loses
`approved`; the run carries on. A `merged` issue left by an interrupted run is closed when its entry is in the
published file, else sent back for re-approval. Exit 1 when the library files have uncommitted changes (a
hand run on a dirty clone), the labels are missing, or a gh or git step fails.
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge import slug  # noqa: E402

def kind_of(title):
    """"Tile: …" → tiles, "Projector: …" → projectors, else None."""
    t = title.strip().lower()
    if t.startswith("tile:"): return "tiles"
    if t.startswith("projector:"): return "projectors"
    return None

def entry_id(body):
    """The id merge.py would assign the issue's entry, or None when the body has no usable JSON block."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", body or "", re.S)
    if not m: return None
    try:
        entry = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    maker, model = entry.get("manufacturer"), entry.get("model")
    if not isinstance(maker, str) or not isinstance(model, str): return None
    return slug(maker.strip(), model.strip())

class Tools:
    def __init__(self, gh, git):
        self.gh_path, self.git_path = gh, git
    def gh(self, *args):
        r = subprocess.run([self.gh_path, *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout
    def git(self, *args):
        r = subprocess.run([self.git_path, *args], capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout

def main(argv):
    try:
        return run(argv)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

def run(argv):
    gh_path, git_path = "gh", "git"
    if "--gh" in argv: gh_path = argv[argv.index("--gh") + 1]
    if "--git" in argv: git_path = argv[argv.index("--git") + 1]
    tools = Tools(gh_path, git_path)

    if tools.git("status", "--porcelain", "--", "tiles.json", "projectors.json").strip():
        print("library files have uncommitted changes; commit or discard them first", file=sys.stderr)
        return 1

    labels = {l["name"] for l in json.loads(tools.gh("label", "list", "--limit", "100", "--json", "name"))}
    missing = [l for l in ("approved", "merged") if l not in labels]
    if missing:
        print(f"missing label(s): {', '.join(missing)}; create them once with gh label create (see README.md)", file=sys.stderr)
        return 1

    approved = json.loads(tools.gh("issue", "list", "--label", "approved", "--state", "open", "--limit", "100", "--json", "number,title,body"))
    gained = {"tiles": [], "projectors": []}
    for issue in sorted(approved, key=lambda i: i["number"]):
        number = str(issue["number"])
        kind = kind_of(issue.get("title", ""))
        if kind is None:
            tools.gh("issue", "comment", number, "--body", "Could not tell whether this is a tile or a projector from the title")
            tools.gh("issue", "edit", number, "--remove-label", "approved")
            continue
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "merge.py"), kind, "--no-bump"], input=issue.get("body", ""), capture_output=True, text=True)
        if r.returncode != 0:
            reason = r.stderr.strip() or r.stdout.strip()
            tools.gh("issue", "comment", number, "--body", f"Could not merge: {reason}")
            tools.gh("issue", "edit", number, "--remove-label", "approved")
            print(f"#{number}: refused, {reason}")
            continue
        gained[kind].append(number)
        tools.gh("issue", "edit", number, "--add-label", "merged", "--remove-label", "approved")
        print(f"#{number}: {r.stdout.strip()}")

    versions = {}
    for kind in ("tiles", "projectors"):
        if gained[kind]:
            out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "publish.py"), kind], capture_output=True, text=True)
            if out.returncode != 0:
                print(out.stderr, file=sys.stderr)
                return 1
            versions[kind] = int(out.stdout.strip().rsplit(" ", 1)[1])
    if versions:
        message = "Publish " + ", ".join(f"{kind} version {v}" for kind, v in versions.items())
        tools.git("add", "tiles.json", "projectors.json")
        tools.git("commit", "-m", message)
        tools.git("push")
        print(message)
    else:
        print("nothing to publish")

    # Close what is published. This run's issues are closed from the driver's own record, since GitHub's listing
    # can lag a label change by seconds; the listing serves only for issues left `merged` by an earlier run
    files = {kind: json.load(open(os.path.join(ROOT, f"{kind}.json"))) for kind in ("tiles", "projectors")}
    closed = set()
    for kind, numbers in gained.items():
        for number in numbers:
            tools.gh("issue", "close", number, "--comment", f"Added in version {versions[kind]}")
            tools.gh("issue", "edit", number, "--remove-label", "merged")
            closed.add(number)
    merged = json.loads(tools.gh("issue", "list", "--label", "merged", "--state", "open", "--limit", "100", "--json", "number,title,body"))
    for issue in sorted(merged, key=lambda i: i["number"]):
        number = str(issue["number"])
        if number in closed:
            continue
        kind = kind_of(issue.get("title", ""))
        wanted = entry_id(issue.get("body", ""))
        present = kind is not None and wanted is not None and any(e["id"] == wanted for e in files[kind]["entries"])
        if present and kind in versions:
            tools.gh("issue", "close", number, "--comment", f"Added in version {versions[kind]}")
            tools.gh("issue", "edit", number, "--remove-label", "merged")
        elif present:
            # In the file but not published by this run: a version already went out with it; close with the current one
            tools.gh("issue", "close", number, "--comment", f"Added in version {files[kind]['version']}")
            tools.gh("issue", "edit", number, "--remove-label", "merged")
        else:
            tools.gh("issue", "comment", number, "--body", "Merged entry not found in the published file; please re-approve")
            tools.gh("issue", "edit", number, "--remove-label", "merged")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

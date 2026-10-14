#!/usr/bin/env python3
"""Merges a submission into tiles.json or projectors.json.

Usage: gh issue view 12 --json body -q .body | python3 scripts/merge.py projectors
       python3 scripts/merge.py tiles submission.md [--no-bump]
Reads the first ```json block, checks it, assigns a slug id, appends it, bumps the version and sets the date,
then runs validate.py. Refuses a duplicate manufacturer and model, a bad number, or duplicate lens names.
With --no-bump the entry is appended and validated but the version and date stay, for publish.py to bump once.
"""
import datetime, json, math, os, re, subprocess, sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def slug(manufacturer, model):
    text = (manufacturer + " " + model).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")

def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

def discontinued(item, ordered, what):
    """Carries a discontinued flag over when the submission gives one; only true or false is accepted."""
    if "discontinued" in item:
        if not isinstance(item["discontinued"], bool):
            fail(f"{what}: discontinued must be true or false")
        ordered["discontinued"] = item["discontinued"]
    return ordered

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or args[0] not in ("tiles", "projectors") or not flags <= {"--no-bump"}:
        fail("usage: merge.py <tiles|projectors> [file] [--no-bump]")
    kind = args[0]
    text = open(args[1]).read() if len(args) > 1 else sys.stdin.read()
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        fail("no ```json block found in the submission")
    try:
        entry = json.loads(m.group(1), parse_constant=lambda c: fail(f"{c} is not a number"))
    except json.JSONDecodeError as e:
        fail(f"the JSON block does not parse: {e}")
    for key in ("manufacturer", "model"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            fail(f"{key} is missing")
    entry["manufacturer"] = entry["manufacturer"].strip()
    entry["model"] = entry["model"].strip()
    entry.pop("source", None)
    entry.pop("id", None)
    if kind == "tiles":
        for key in ("tileResolution", "tileSize"):
            v = entry.get(key, {})
            if not (isinstance(v, dict) and is_number(v.get("width")) and is_number(v.get("height")) and v["width"] > 0 and v["height"] > 0):
                fail(f"{key} must have width and height above zero")
        t = entry.get("transparency")
        if t is not None and not (is_number(t) and 0 <= t <= 100):
            fail("transparency must be null or 0–100")
        ordered = {"id": None, "manufacturer": entry["manufacturer"], "model": entry["model"],
                   "tileResolution": entry["tileResolution"], "tileSize": entry["tileSize"], "transparency": t}
    else:
        v = entry.get("resolution", {})
        if not (isinstance(v, dict) and is_number(v.get("width")) and is_number(v.get("height")) and v["width"] > 0 and v["height"] > 0):
            fail("resolution must have width and height above zero")
        lumens = entry.get("lumens", 0)
        if not is_number(lumens) or lumens < 0:
            fail("lumens must be a number from 0")
        lenses = []
        names = set()
        for lens in entry.get("lenses", []):
            name = str(lens.get("name", "")).strip()
            if not name:
                fail("every lens needs a name")
            if name in names:
                fail(f"duplicate lens name {name}")
            names.add(name)
            lo, hi = lens.get("throwMin"), lens.get("throwMax")
            if not is_number(lo):
                fail(f"lens {name}: throwMin must be a number")
            lo = min(max(0.1, lo), 20)
            if hi is not None:
                if not is_number(hi):
                    fail(f"lens {name}: throwMax must be a number or null")
                hi = min(max(0.1, hi), 20)
                if hi < lo:
                    lo, hi = hi, lo
            lenses.append(discontinued(lens, {"name": name, "throwMin": lo, "throwMax": hi}, f"lens {name}"))
        ordered = discontinued(entry, {"id": None, "manufacturer": entry["manufacturer"], "model": entry["model"],
                                       "resolution": v, "lumens": lumens, "lenses": lenses}, "the projector")
    path = os.path.join(ROOT, f"{kind}.json")
    data = json.load(open(path))
    new_id = slug(ordered["manufacturer"], ordered["model"])
    if not new_id:
        fail("manufacturer and model need at least one letter or digit between them")
    for existing in data["entries"]:
        if existing["id"] == new_id or (existing["manufacturer"].lower() == ordered["manufacturer"].lower() and existing["model"].lower() == ordered["model"].lower()):
            fail(f"{ordered['manufacturer']} {ordered['model']} is already in {kind}.json as {existing['id']}")
    ordered["id"] = new_id
    data["entries"].append(ordered)
    if "--no-bump" not in flags:
        data["version"] = int(data["version"]) + 1
        data["updated"] = datetime.date.today().isoformat()
    original = open(path).read()   # put back if the validator refuses, so a bad entry never stays in the file
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    result = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "validate.py")], capture_output=True, text=True)
    if result.returncode != 0:
        open(path, "w").write(original)
        fail("validate.py failed after the merge:\n" + result.stderr)
    if "--no-bump" in flags:
        print(f"added {new_id} to {kind}.json (unpublished)")
    else:
        print(f"added {new_id} to {kind}.json, now version {data['version']}")

if __name__ == "__main__":
    main()

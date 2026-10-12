#!/usr/bin/env python3
"""Checks tiles.json and projectors.json: shape, numbers, unique ids, unique lens names. Exit 1 on any problem."""
import json, os, sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems = []

def positive(entry, key, where):
    v = entry.get(key)
    if not isinstance(v, dict) or not is_number(v.get("width")) or not is_number(v.get("height")) or v["width"] <= 0 or v["height"] <= 0:
        problems.append(f"{where}: {key} must have width and height above zero")

def check_file(name, check_entry):
    path = os.path.join(ROOT, name)
    try:
        data = json.load(open(path))
    except Exception as e:
        problems.append(f"{name}: not valid JSON ({e})")
        return
    if not isinstance(data.get("version"), int) or data["version"] < 1:
        problems.append(f"{name}: version must be a whole number from 1")
    if not isinstance(data.get("updated"), str) or len(data["updated"]) != 10:
        problems.append(f"{name}: updated must be YYYY-MM-DD")
    entries = data.get("entries")
    if not isinstance(entries, list):
        problems.append(f"{name}: entries must be a list")
        return
    ids = set()
    for i, entry in enumerate(entries):
        where = f"{name} entry {i}"
        for key in ("id", "manufacturer", "model"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                problems.append(f"{where}: {key} must be a non-empty string")
        if entry.get("id") in ids:
            problems.append(f"{where}: duplicate id {entry.get('id')}")
        ids.add(entry.get("id"))
        if "source" in entry:
            problems.append(f"{where}: repository entries carry no source")
        check_entry(entry, where)

def check_tile(entry, where):
    positive(entry, "tileResolution", where)
    positive(entry, "tileSize", where)
    t = entry.get("transparency")
    if t is not None and (not is_number(t) or t < 0 or t > 100):
        problems.append(f"{where}: transparency must be null or 0–100")

def check_projector(entry, where):
    positive(entry, "resolution", where)
    if not is_number(entry.get("lumens")) or entry["lumens"] < 0:
        problems.append(f"{where}: lumens must be a number from 0")
    lenses = entry.get("lenses")
    if not isinstance(lenses, list):
        problems.append(f"{where}: lenses must be a list")
        return
    names = set()
    for j, lens in enumerate(lenses):
        lw = f"{where} lens {j}"
        name = lens.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{lw}: name must be a non-empty string")
        if name in names:
            problems.append(f"{lw}: duplicate lens name {name}")
        names.add(name)
        lo, hi = lens.get("throwMin"), lens.get("throwMax")
        if not is_number(lo) or not 0.1 <= lo <= 20:
            problems.append(f"{lw}: throwMin must be 0.1–20")
        if hi is not None and (not is_number(hi) or not 0.1 <= hi <= 20 or hi < lo):
            problems.append(f"{lw}: throwMax must be null or 0.1–20 and not below throwMin")

check_file("tiles.json", check_tile)
check_file("projectors.json", check_projector)
for p in problems:
    print(p, file=sys.stderr)
sys.exit(1 if problems else 0)

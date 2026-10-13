# PixelWraith Grid device library

`tiles.json` and `projectors.json` are the LED tiles and projectors that PixelWraith Grid downloads at launch (and from Settings ▸ Check Now). Each file carries a `version` the app compares; the app only applies a file whose version is higher than the one it has.

A projector or lens the maker no longer sells carries `"discontinued": true`; the app marks it "discontinued" in the Projector Library and the Lens pop-up. Leave the field out for a current product.

## Submitting an entry

In the app, select your entry in the Tile Library or Projector Library and press Submit to Library… (or right-click the row). The app sends it to the relay in `relay/`, which opens an issue here labelled `submission`; no GitHub account is needed. Offline, the app keeps it and sends it at its next launch. You can also open a new issue from the Tile or Projector template and fill in the JSON. Add a spec-sheet link.

## Approving (maintainer)

From the repository root, with the issue's number (`gh issue list` shows them) and the kind, `tiles` or
`projectors`:

```
gh issue list
gh issue view 12 --json body -q .body | python3 scripts/merge.py tiles
git commit -am "Add PixelFLEX FLEXTour 1.95" && git push
gh issue close 12 --comment "Added in version 5"
```

The merge script reads the issue body from the pipe, assigns the id, appends the entry, bumps the file's version
and validates; the app applies the file at its next check because the version went up.

`scripts/validate.py` runs on every push; `scripts/test_scripts.py` exercises both scripts.

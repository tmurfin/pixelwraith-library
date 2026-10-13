# PixelWraith Grid device library

`tiles.json` and `projectors.json` are the LED tiles and projectors that PixelWraith Grid downloads at launch (and from Settings ▸ Check Now). Each file carries a `version` the app compares; the app only applies a file whose version is higher than the one it has.

A projector or lens the maker no longer sells carries `"discontinued": true`; the app marks it "discontinued" in the Projector Library and the Lens pop-up. Leave the field out for a current product.

## Submitting an entry

In the app, right-click your entry in the Tile Library or Projector Library and choose Submit to the Library…; it opens a prefilled issue here. Or open a new issue from the Tile or Projector template and fill in the JSON. Add a spec-sheet link.

## Approving (maintainer)

```
gh issue view <number> --json body -q .body | python3 scripts/merge.py <tiles|projectors>
git commit -am "Add <manufacturer> <model>" && git push
gh issue close <number> --comment "Added in version <n>"
```

`scripts/validate.py` runs on every push; `scripts/test_scripts.py` exercises both scripts.

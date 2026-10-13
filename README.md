# PixelWraith Grid device library

`tiles.json` and `projectors.json` are the LED tiles and projectors that PixelWraith Grid downloads at launch and
from Settings ▸ Check Now. Each file carries a `version`; the app applies a file only when its version is higher
than the one it already has, so every change to a file must raise its version by one.

A projector or lens the maker no longer sells carries `"discontinued": true`; the app shows a discontinued mark
in the Projector Library and the Lens pop-up. Leave the field out for a current product.

## Submitting an entry (anyone)

In the app, select your entry in the Tile Library or Projector Library and press Submit to Library…, or
right-click the row. The app sends it to the relay in `relay/`, which opens an issue here labelled `submission`.
No GitHub account is needed. Offline, the app keeps the submission and sends it at its next launch. Add a
spec-sheet link in the sheet so the maintainer can check the numbers.

You can also open a new issue by hand from the Tile or Projector template and fill in the JSON.

## Updating the library (maintainer)

### Once, on your machine

- Clone this repository and open a terminal **at its root** (the folder that holds `tiles.json`). Every command
  below runs from there; from any other folder the script path is wrong.
- Install the GitHub CLI and sign in: `gh auth login`.
- Python 3 is the only other requirement.

### Each submission

1. See what is waiting:

   ```
   gh issue list
   ```

   Each line starts with the issue number, for example `#12`. The title says what it is: "Tile: …" or
   "Projector: …".

2. Read it and check the numbers against the spec sheet:

   ```
   gh issue view 12
   ```

3. Merge it. Replace `12` with the issue's number and the last word with the kind, `tiles` for a tile or
   `projectors` for a projector:

   ```
   gh issue view 12 --json body -q .body | python3 scripts/merge.py tiles
   ```

   The script reads the issue's JSON block, assigns the id, appends the entry, raises the file's version, sets
   the date and validates the file. It prints `added <id> to tiles.json, now version <n>`. It changes nothing
   and prints the reason when an entry already exists with that manufacturer and model, a number is missing or
   below zero, or two lenses share a name; fix the issue text or ask the submitter, then run it again.

4. Publish:

   ```
   git commit -am "Add <manufacturer> <model>" && git push
   ```

   The push runs the validator and the relay test on GitHub. `gh run list --limit 1` shows the result.

5. Tell the submitter and close the issue, using the version the merge printed:

   ```
   gh issue close 12 --comment "Added in version 6"
   ```

Several submissions can be merged in a row before one commit; each merge raises the version again.

### Editing by hand

To correct a value or add an entry without an issue, edit the JSON, raise `version` by one, set `updated` to
today's date (`YYYY-MM-DD`), then check it before committing:

```
python3 scripts/validate.py
```

### How the app picks it up

Every copy of the app checks at launch, and from Settings ▸ Check Now, and applies a file whose version went
up. The Settings line then reads "Updated tiles to version 6". If the submitter's own copy of the entry sits
under Mine, the app removes it and says so: "Removed from Mine: …".

GitHub serves these files through a cache that holds a file for about five minutes after a push. A check inside
that window still sees the old version and reads "Up to date"; check again a few minutes later.

### If something does not work

- `can't open file '…/scripts/merge.py'`: the terminal is not at the repository root. `cd` there and retry.
- `zsh: parse error`: a placeholder such as `<number>` was typed literally. Replace it with the real number.
- `resolution must have width and height above zero` on a tile, or a similar complaint about a tile field on a
  projector: the kind at the end of the merge command does not match the issue. Use `tiles` for "Tile:" issues
  and `projectors` for "Projector:" issues.
- `nothing to commit, working tree clean` after the merge: the merge did not run (see the two lines above), so
  there is nothing new to publish yet.
- The relay stops opening issues and the app shows a clock on submitted entries: the GitHub token stored in
  the worker has lapsed. Create a new fine-grained token and store it again, as described in `relay/README.md`.

## Relay

`relay/` holds the Cloudflare Worker the app submits through, its test, its rate limit (ten submissions a minute
per address) and the deploy steps. `node --test
relay/worker.test.mjs` runs its test; the push workflow runs it too.

## Scripts

- `scripts/merge.py <tiles|projectors>` merges one submission read from standard input (the pipe above) or
  from a file given as a second argument.
- `scripts/validate.py` checks both library files; it runs on every push.
- `scripts/test_scripts.py` exercises both scripts against fixtures.

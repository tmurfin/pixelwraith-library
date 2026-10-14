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
- Create the labels the review and the Publish workflow use, once per repository:

  ```
  gh label create needs-changes --description "Sent back to the submitter" --color d93f0b
  gh label create approved --description "Goes out in the next version" --color 0e8a16
  gh label create merged --description "In the next version, not yet published" --color bfd4f2
  ```
- Python 3 is the only other requirement.

### Reviewing

Each submission is an issue. Read it (`gh issue view 12`, or on the issue page), check the numbers against
the spec sheet, then decide with a label:

- `approved`: it goes out in the next version. `gh issue edit 12 --add-label approved`, or the Labels menu on
  the issue page.
- `needs-changes` with a comment saying what to fix:

  ```
  gh issue edit 12 --add-label needs-changes
  gh issue comment 12 --body "Add the pitch to the model name"
  ```

  The submitter sees the comment in the app at their next check, edits the entry and resubmits, which reopens
  the issue, takes the label off and comments "Updated from the app."
- Close it with a comment to decline for good.

An issue filed by hand can be edited by its author after you label it; the workflow merges the body as it is
at publish time, so glance at an issue marked "edited" before you publish. Issues the app files can only change
through the app, which takes the label off again.

### Publishing

When a version should go out, run the Publish workflow from the repository's Actions tab, or:

```
gh workflow run publish.yml
```

It merges every `approved` issue, raises each changed file's version once, commits "Publish tiles version 7"
to main, pushes, and closes the issues with "Added in version 7". An issue the merge script refuses (a model
already in the library, a bad number) gets the reason as a comment and loses `approved`; the rest still go
out. `gh run watch` follows the run. The apps pick the version up at their next check, and the submitter's
own copy of each entry is removed from Mine.

### A one-off without the workflow

From the repository root, with the issue's number and the kind, `tiles` or `projectors`:

```
gh issue view 12 --json body -q .body | python3 scripts/merge.py tiles
git commit -am "Add PixelFLEX FLEXTour 1.95" && git push
gh issue close 12 --comment "Added in version 6"
```

This merges and publishes in one step (the version goes up by one). To stage several by hand instead, add
`--no-bump` to each merge, then `python3 scripts/publish.py tiles` once before the commit.

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
- The Publish run stops with `missing label(s)`: create the labels from the setup above.
- A run cannot close an issue with a version its entry is not in: a `merged` issue whose entry is missing from
  the published file is sent back with a comment instead.
- The relay stops opening issues and the app shows a clock on submitted entries: the GitHub token stored in
  the worker has lapsed. Create a new fine-grained token and store it again, as described in `relay/README.md`.

## Relay

`relay/` holds the Cloudflare Worker the app submits through, its test, its rate limit (sixty posts a minute
per address) and the deploy steps. `node --test
relay/worker.test.mjs` runs its test; the push workflow runs it too.

## Scripts

- `scripts/merge.py <tiles|projectors> [file] [--no-bump]` merges one submission read from standard input (the
  pipe above) or from a file; with `--no-bump` it leaves the version and date for `publish.py`.
- `scripts/publish.py <tiles|projectors|both>` raises a file's version by one, sets its date and validates.
- `scripts/publish_approved.py` merges every `approved` issue without bumping, publishes each changed kind once,
  commits, pushes and closes the issues; the Publish workflow runs it.
- `scripts/validate.py` checks both library files; it runs on every push.
- `scripts/test_scripts.py` exercises the scripts against fixtures, the publish driver against a fake `gh` and
  `git` included.

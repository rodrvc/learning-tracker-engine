# ui - progress visualization CLI

Standard library CLI (`argparse`, no dependencies) over the public API of
`LearningTracker`. This layer **computes nothing**: it shows what the engine
answers. It does not import `core.leveling` or `core.scheduling`, and it does
not read attempts from the store on its own (an AST test verifies that).

The CLI speaks Spanish to the user: the subcommand names are in English but the
messages it prints are in Spanish, and the tests assert them as such.

## Install

```sh
pip install .          # puts the learning-tracker executable on the PATH
learning-tracker --help
```

Without installing, from the root of the repo, `python -m ui ...` does exactly
the same. The examples below use `python -m ui`; swap the prefix for
`learning-tracker` if you installed it.

## Usage

```
learning-tracker [--data DIR] [--profile ID] [--as-of ISO8601] COMMAND ...
python -m ui      [--data DIR] [--profile ID] [--as-of ISO8601] COMMAND ...
```

- `--data DIR`: directory holding `profiles.json` and `attempts.json`. Without
  this argument the user directory of the operating system is used (see "Where
  the data lives").
- `--profile ID`: profile to operate on. Mandatory except in `profile`.
- `--as-of ISO8601`: query date. When missing the system clock is used. A date
  without a timezone is assumed to be UTC; the `Z` suffix is accepted.

Commands:

| Command | What it does |
| --- | --- |
| `profile create ID --name NAME` / `profile list` | Creates or lists profiles |
| `objective add ID --title T [--domain D] [--weight W]` | Adds or replaces an objective |
| `objectives` | Catalog of the profile with level and score at `--as-of` |
| `record ID --correct\|--wrong [--at ISO] [--kind K] [--confidence C] [--note N] [--id X]` | Records an attempt. Without `--at` it uses `--as-of` or the clock |
| `state ID` | Complete state of an objective (SPEC section 1.5) |
| `due [--limit N]` | What is due for review, by urgency (SPEC section 5.2) |
| `unstarted` | Objectives without a single attempt |
| `stale [--days N]` | Objectives with no activity in N days (default 14) |
| `summary` | Profile aggregate: split by level, coverage |
| `timeline ID --start ISO --end ISO [--step-days N]` | Time series (SPEC section 5.3) |
| `compare ID --earlier ISO --later ISO` | "Was I better two weeks ago?" (SPEC section 5.1) |
| `check` | Consistency check by counts (SPEC section 8, failure 2) |

Exit codes: `0` ok; `1` only in `check` when `ok=False`; `2` a usage or domain
error (`UnknownObjectiveError`, `DuplicateAttemptError`, `InvalidAttemptError`,
`StorageError`...). Never a traceback.

## Where the data lives

The data belongs to the user, not to the repo: it lives in the standard folder
of their operating system, not in a `./data` relative to the current directory
(that way the CLI always opens the same store no matter where it is run from).

| System | Default directory |
| --- | --- |
| macOS | `~/Library/Application Support/learning-tracker` |
| Linux and the rest | `$XDG_DATA_HOME/learning-tracker`, or `~/.local/share/learning-tracker` when `XDG_DATA_HOME` is not defined |

Precedence, highest to lowest:

1. `--data DIR` on the command line.
2. The environment variable `LEARNING_TRACKER_DATA`.
3. The operating system default from the table.

`learning-tracker --help` shows the effective default on your machine. The
directory is created on the fly with `0700` permissions (only its owner gets in)
and the JSON files inside are still written exactly as always.

If you had data in a `./data` from an earlier version, the CLI detects it on
start-up and prints to stderr the exact command to move it. **It does not move
or copy anything on its own**: the notice goes away once the new destination
holds data. You can also stay where you were with
`LEARNING_TRACKER_DATA=/path/to/data`.

## Backup

Copying the whole data directory is the entire backup:

```sh
cp -R "$HOME/Library/Application Support/learning-tracker" ~/backup-learning-tracker
```

Restoring is copying it back. The `.lock` files are empty files used for
exclusion between processes: there is no need to copy them, and they are
recreated on their own on the next write.

## Concurrency of the JSON backend

Every write (recording an attempt, creating a profile, adding objectives) takes
an exclusive lock (`flock`) over an empty file `attempts.json.lock` /
`profiles.json.lock` next to the JSON, so two CLIs writing at the same time into
the same `--data` do not overwrite each other: the second waits for the first to
finish. The guarantee holds for processes on the same host; on network file
systems (NFS, SMB) `flock` is not reliable and there is no exclusion. The
`.lock` files can be deleted safely: they are recreated on the next write.

## Examples

```sh
# Create a profile and an objective
python -m ui profile create ai-103 --name "Azure AI-103"
python -m ui --profile ai-103 objective add D3.2 --title "Content understanding" --domain D3

# Record the series "wrong, wrong, wrong, right, wrong" on injected dates
for d in 01 02 03; do python -m ui --profile ai-103 record D3.2 --wrong --at 2026-01-${d}T10:00Z; done
python -m ui --profile ai-103 record D3.2 --correct --at 2026-01-04T10:00Z
python -m ui --profile ai-103 record D3.2 --wrong   --at 2026-01-05T10:00Z

# How did it look on January 3rd? (it does not change when later attempts arrive)
python -m ui --profile ai-103 --as-of 2026-01-03T12:00Z state D3.2

# Was it better two weeks ago? And what is due for review today
python -m ui --profile ai-103 compare D3.2 --earlier 2026-02-15 --later 2026-03-01
python -m ui --profile ai-103 due --limit 5
```

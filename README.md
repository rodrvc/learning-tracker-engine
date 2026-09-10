# learning-tracker

Learning tracking engine: it records attempts, computes a mastery level per
objective and schedules reviews. Independent of whatever subject is being
studied.

**Status:** under construction. The contract lives in `SPEC.md`.

## Principles

- **The history is the only source of truth.** Every aggregate (level, next
  review) is a recalculable projection. Nothing is stored that cannot be
  derived.
- **Time is injected, never read.** The engine does not call `now()`: it
  receives the date. That is what makes it possible to simulate months of study
  inside a test.
- **Modular.** `core/` knows nothing about storage, about the CLI or about the
  UI.

## Install and use

```sh
pip install .                       # puts the learning-tracker executable on the PATH
learning-tracker --help
```

Without installing, from the root of the repo, `python -m ui ...` does the same
thing. The detail of every subcommand is in `ui/README.md`.

## Where the data lives

The data belongs to the user, not to the repo. By default it lives in the
standard folder of the operating system, not in a `./data` relative to the
current directory: that way the CLI always opens the same store no matter where
it is run from, and whoever clones the repo does not end up with their data
inside the project.

| System | Default directory |
| --- | --- |
| macOS | `~/Library/Application Support/learning-tracker` |
| Linux and the rest | `$XDG_DATA_HOME/learning-tracker`, or `~/.local/share/learning-tracker` when `XDG_DATA_HOME` is not defined |

Precedence: `--data DIR` beats the environment variable
`LEARNING_TRACKER_DATA`, which beats the operating system default.
`learning-tracker --help` shows the effective default on your machine. The
directory is created with `0700` permissions: only its owner gets in.

If you had data in a `./data` from an earlier version, the CLI detects it and
prints to stderr the exact command to move it, then carries on with the new
destination. It does not move or copy anything on its own.

## Backup

Copy the whole data directory:

```sh
cp -R "$HOME/Library/Application Support/learning-tracker" ~/backup-learning-tracker
```

Restoring is copying it back. The `.lock` files inside are empty files used for
exclusion between processes: there is no need to copy them, and they are
recreated on the next write.

## Layout

| Path | What it is |
| --- | --- |
| `SPEC.md` | The contract: levels, evolution, guarantees |
| `core/` | Pure engine, no I/O |
| `store/` | Persistence |
| `tests/` | Verification suite |
| `ui/` | Progress visualization |

## Language

The code, the documentation and the commit messages are in English. What the
CLI prints to the user is in Spanish.

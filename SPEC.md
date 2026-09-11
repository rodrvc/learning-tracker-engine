# SPEC - Contract of the learning tracking engine

Version 1.0 - 2026-09-02

This document is **the contract**. The code in `core/` is empty signatures; the
only source of truth about behaviour is this file. If the code and the spec
disagree, **the spec wins**.

It is written so that two people who do not talk to each other - whoever
implements and whoever tests - arrive at the same result. That is why every rule
carries numbers and every example is walked through step by step.

---

## 0. Vocabulary and underlying decisions

| Term | What it is |
| --- | --- |
| **Profile** (`Profile`) | A study subject with its objectives. E.g.: "AI-103". It is the root container. |
| **Objective** (`Objective`) | A unit of knowledge that can be assessed. E.g.: "choosing between Azure AI Search and manual RAG". |
| **Attempt** (`Attempt`) | A fact that happened: on this date, on this objective, the answer was right or wrong. **Immutable.** |
| **Level** (`Level`) | A **projection** computed from the attempt history. It is never stored as truth. |
| **Snapshot** (`Snapshot`) | The level of one objective, or of all of them, **as it was at a given date**. |

### The three decisions that govern everything else

1. **The attempt history is the only persistent data.** Level, next review,
   statistics: everything is recomputed. There are no cumulative counters that
   can get corrupted, because there are no counters: there is a list of facts.
2. **Time always arrives as a parameter.** No function in `core/` reads the
   system clock. Whoever needs "today" receives a `Clock` or an explicit date.
3. **Every query accepts an `as_of` (cut date).** Asking for the level is, in
   truth, asking for the level *at a date*. When it is not given, the date of
   the injected clock is used. There is no "timeless" query.

---

## 1. Data model

### 1.1 Profile - `Profile`

| Field | Type | Description |
| --- | --- | --- |
| `profile_id` | `str` | Stable identifier. E.g.: `"ai-103"`. Unique. |
| `name` | `str` | Human readable name. E.g.: `"Microsoft AI-103"`. |
| `objectives` | `dict[str, Objective]` | Objectives indexed by `objective_id`. |

A profile has no progress state of its own: its progress is the aggregation of
that of its objectives. Multi-profile works because each profile is an
independent container and no `objective_id` crosses profile boundaries.

### 1.2 Objective - `Objective`

| Field | Type | Description |
| --- | --- | --- |
| `objective_id` | `str` | Unique **within the profile**. E.g.: `"D3.2-content-understanding"`. |
| `title` | `str` | Human readable description. |
| `domain` | `str \| None` | Optional grouping. E.g.: `"D3"`. |
| `weight` | `float` | Relative weight in the exam, `1.0` by default. Informational only: **it does not affect the level**. |

An objective **does not store** level, run, counters or review date. All of that
is derived. This is deliberate (see section 8, failures 1 and 3).

### 1.3 Attempt - `Attempt`

| Field | Type | Description |
| --- | --- | --- |
| `attempt_id` | `str` | Unique, immutable identifier of the attempt. |
| `objective_id` | `str` | Which objective it belongs to. |
| `at` | `datetime` | **When it happened.** With a timezone (UTC recommended). Injected by whoever records; the engine does not generate it. |
| `correct` | `bool` | `True` = hit, `False` = miss. It is the only binary axis. |
| `kind` | `AttemptKind` | Nature of the evidence: `QUIZ`, `EXERCISE`, `LAB`, `EXAM_SIM`, `SELF_REPORT`. |
| `confidence` | `float \| None` | 0.0-1.0, optional self assessment. **It does not affect the level** in v1. |
| `note` | `str \| None` | Free text. E.g.: the question, or why it failed. |
| `recorded_at` | `datetime \| None` | When it was written to the store, if it differs from `at`. Audit only. |

**An attempt is never modified or deleted.** If there was a recording mistake, a
corrective attempt is added or it is noted in `note`; the history is
append-only.

### 1.4 Level - `Level`

An **ordered** enum. The numeric values exist so that levels can be compared and
plotted ("was I better two weeks ago?" is `level_two_weeks_ago > level_today`).

| Level | Value | Meaning |
| --- | --- | --- |
| `UNASSESSED` | 0 | Not enough evidence. |
| `WEAK` | 1 | Fails the basics. |
| `LEARNING` | 2 | Understands it, misses details. |
| `COMPETENT` | 3 | Answers correctly and consistently. |
| `MASTERED` | 4 | Answers correctly and consistently, sustained over time. |

### 1.5 State of an objective - `ObjectiveState`

What a query returns. **Every one of its fields is derived**, none is persisted.

| Field | Type | Description |
| --- | --- | --- |
| `objective_id` | `str` | - |
| `as_of` | `datetime` | Cut date it was computed with. |
| `level` | `Level` | Level according to section 2. |
| `score` | `float` | Continuous score 0.0-1.0 that produces the level (section 2.2). It allows two objectives of the same level to be compared. |
| `total_attempts` | `int` | Attempts with `at <= as_of`. |
| `correct_attempts` | `int` | Of those, how many were `correct=True`. |
| `recent_window` | `tuple[bool, ...]` | The last `N=8` results up to `as_of`, **from oldest to most recent**. |
| `first_attempt_at` | `datetime \| None` | - |
| `last_attempt_at` | `datetime \| None` | - |
| `distinct_days` | `int` | Number of **distinct calendar days** with at least one attempt. |
| `days_since_last` | `float \| None` | Fractional days between the last attempt and `as_of`. It is the `gap` that feeds the decay (section 2.2). `None` when there are no attempts. |
| `retention` | `float` | Decay factor applied, in `[RETENTION_FLOOR, 1.0]` (section 2.2). |
| `next_review_at` | `datetime \| None` | Next review according to section 4. `None` when there are no attempts. |
| `is_due` | `bool` | `next_review_at <= as_of`. |

Note that there is **no `streak` field**. It is forbidden by design (section 8,
failure 1).

---

## 2. How the level is computed

The level is **a pure function of the set of attempts with `at <= as_of`**. Same
history and same cut date implies the same level, always, on any machine and in
any insertion order.

### 2.1 Constants

| Constant | Value | What it is |
| --- | --- | --- |
| `WINDOW` | `8` | How many recent attempts make up the window. |
| `MIN_ATTEMPTS` | `2` | Minimum attempts to leave `UNASSESSED`. |
| `DECAY_HALF_LIFE_DAYS` | `90` | Every 90 days without activity, retention is halved. |
| `RETENTION_FLOOR` | `0.40` | Floor of the retention factor. **It affects `retention` only, never `raw`.** |
| `MASTERY_MIN_DAYS` | `2` | Distinct calendar days with attempts required for `MASTERED`. |
| `MASTERY_MIN_SPAN_DAYS` | `7` | Days between the first and the last attempt required for `MASTERED`. |
| `MASTERY_MIN_RAW` | `0.95` | Minimum `raw` to be promoted to `MASTERED` (see section 2.4). |

### 2.2 Step by step

**Step 1 - Filter and sort.**
Take every attempt of the objective with `at <= as_of`. Sort them by ascending
`at`. On an exact tie of `at`, break the tie by ascending `attempt_id`
(lexicographic). This tie break makes the result independent of the insertion
order (section 7, edge case 3).

Let `n` be the resulting total.

**Step 2 - If `n < MIN_ATTEMPTS` (that is, 0 or 1 attempt) implies
`UNASSESSED`.**
`score = 0.0`. It stops here. A single hit is not evidence.

**Step 3 - Recent window.**
Take the last `min(n, WINDOW)` attempts of the sorted list. Let `w` be its size.
Assign each one a **positional weight**: the most recent weighs `w`, the next
one `w-1`, ... and the oldest of the window weighs `1`.

Example with `w=8`, from oldest to most recent: weights `1, 2, 3, 4, 5, 6, 7, 8`
(sum **36**).

A window of 8 and not of 5 because the user answers **isolated questions**, not
full exams: with a short window a single answer moved the level too much. With
8, going up demands sustained evidence.

**Step 4 - Raw score.**

```
raw = (sum of the weights of the CORRECT attempts of the window)
      / (sum of every weight of the window)
```

`raw` is in `[0.0, 1.0]`. Weighting by recency is what makes the trend show:
missing the latest weighs more than having missed at the beginning.

**Step 5 - Decay through inactivity.**
Let `gap = (as_of - last_attempt_at)` in days (fractional, not rounded).

```
retention = max(RETENTION_FLOOR, 0.5 ** (gap / DECAY_HALF_LIFE_DAYS))
score     = raw * retention
```

If `gap <= 0`, `retention = 1.0`.

Knowledge rusts, but it does not evaporate. Two decisive nuances:

**The floor applies ONLY to `retention`, never to `raw`.** That is the reason
the floor exists: time can take you from mastered down to weak, **but not to
zero**.

| Situation | `raw` | `retention` | `score` | Reading |
| --- | --- | --- | --- | --- |
| Mastered and abandoned for a year | 1.00 | 0.40 (floor) | **0.400** | "I abandoned it" |
| Always missed, just seen | 0.10 | 1.00 | **0.100** | "I don't know it" |
| Always missed and abandoned | 0.10 | 0.40 (floor) | **0.040** | both things |

Without the floor, both cases converged to ~0 and the score could not tell *I
parked it* apart from *I never understood it*, which demand different actions:
reviewing versus studying from scratch.

**Retention table** (verified, `HL=90`, floor `0.40`):

| `gap` | 0 d | 7 d | 15 d | 30 d | 60 d | 90 d | 180 d | 365 d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `retention` | 1.000 | 0.948 | 0.891 | 0.794 | 0.630 | 0.500 | 0.400 | 0.400 |

From about 119 days on, the floor dominates and retention no longer falls.

**Step 6 - Thresholds.** The `score` is translated into a level:

| Condition on `score` | Level |
| --- | --- |
| `score >= 0.85` | `COMPETENT` (candidate for `MASTERED`, see step 7) |
| `0.60 <= score < 0.85` | `LEARNING` |
| `score < 0.60` | `WEAK` |

The thresholds are **closed from below**: exactly `0.85` is `COMPETENT`, exactly
`0.60` is `LEARNING`.

**Step 7 - Promotion to `MASTERED`.**
A `COMPETENT` candidate rises to `MASTERED` **only if it also** meets the three
sustain-over-time conditions:

1. `distinct_days >= MASTERY_MIN_DAYS` (2), where a calendar day is the date
   **in UTC** of the instant `at`, whatever the timezone it was recorded with,
   and
2. `(last_attempt_at - first_attempt_at) >= MASTERY_MIN_SPAN_DAYS` (7 days), and
3. `raw >= MASTERY_MIN_RAW` (0.95) - see section 2.4 on why 0.95 and not 1.0.

If it does not meet them, it stays `COMPETENT`. You cannot master something in
one afternoon: it is the numeric translation of "evidence across 2 or more
separate sessions".

### 2.4 Why `MASTERED` demands `raw >= 0.95` and not `raw == 1.0`

When the window moved from 5 to 8, it was reviewed whether the thresholds still
made sense. **The level thresholds (0.85 / 0.60) stay**: they remain reachable
and well spaced with a window of 8 - 5 final hits out of 8 give `raw = 0.833`, 6
give `0.917`. There is no reason to move them.

**The `MASTERED` criterion was adjusted**, from `raw == 1.0` to `raw >= 0.95`.
With a window of 5, demanding perfection meant 5 hits in a row. With a window of
8 it means **8 consecutive hits without a single miss**, and on top of that any
miss takes **8 more attempts** to leave the window. The measured effect:

| Window | `raw` | `raw == 1.0`? | `raw >= 0.95`? |
| --- | --- | --- | --- |
| 8 hits | 1.000 | yes | yes |
| 7 hits + 1 miss in the **oldest** position (weight 1) | 0.972 | no | **yes** |
| 7 hits + 1 miss in the second oldest position (weight 2) | 0.944 | no | no |

With `raw == 1.0`, a single old and almost purged miss blocked the promotion for
eight more attempts, which made `MASTERED` practically unreachable for someone
answering isolated questions. `0.95` lets exactly that case through - a residual
miss in the lowest weight position - and still rejects any more recent miss. The
other two conditions (2 or more distinct days, span of 7 or more days) are not
touched: they are the ones that prevent mastering something in one afternoon.

Note as well that `MASTERED` demands `score >= 0.85`, and with `raw = 1.0` the
score drops below 0.85 after **22 days** of inactivity (the exact crossing is at
`gap = 21.1019` days: on day 21 the score is 0.8507 and the objective **is
still** `MASTERED`; on day 22 it is 0.8441 and it falls straight to `LEARNING`,
because below 0.85 there is no intermediate stretch - `COMPETENT` only exists as
a step when `raw` does not reach 0.95). `MASTERED` remains, by design, a state
that has to be sustained.

It is worth underlining why decay **can** make `MASTERED` be lost even though
the three sustain conditions of step 7 are immune to the passage of time:
`retention` touches neither `raw`, nor `distinct_days`, nor the span, so those
three keep holding forever. The only thing that falls is the `score`, and with
it the prior condition of being a candidate (`score >= 0.85`) from step 6. An
abandoned objective stops being `MASTERED` by stopping being `COMPETENT`, not by
stopping being sustained.

### 2.3 Executable summary in one line

> Level = threshold(weighted_recency(last 8) x decay with a floor of 0.40), with
> `MASTERED` reserved for the almost perfect and sustained for 7 or more days.

---

## 3. Evolution: the walkthrough of "wrong, wrong, wrong, right, wrong"

The canonical scenario. Objective `X`, five attempts on **consecutive days** so
that decay is almost neutral. `as_of` = the instant of the last attempt on each
row, so `gap = 0` and `retention = 1.0` (except on the last row).

| # | Date | Result | Window (old->new) | Hits/Total | `raw` | `score` | **Level** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-01-01 | wrong | `[F]` | - | - | 0.000 | `UNASSESSED` (n=1 < 2) |
| 2 | 2026-01-02 | wrong | `[F,F]` | 0 / 3 | 0.000 | 0.000 | `WEAK` |
| 3 | 2026-01-03 | wrong | `[F,F,F]` | 0 / 6 | 0.000 | 0.000 | `WEAK` |
| 4 | 2026-01-04 | **right** | `[F,F,F,C]` | 4 / 10 | 0.400 | 0.400 | `WEAK` |
| 5 | 2026-01-05 | wrong | `[F,F,F,C,F]` | 4 / 15 | 0.267 | 0.267 | `WEAK` |

Note that with only 5 attempts the window (which admits 8) is not full yet: the
weights are `1..n`, not `1..8`.

Check of row 4: the only hit is the most recent of a window of 4, so it weighs
`4`. Sum of weights `1+2+3+4 = 10`. `raw = 4/10 = 0.400`.

Check of row 5: the window is of 5, the hit ended up in the second to last
position and weighs `4`. Sum of weights `1+2+3+4+5 = 15`.
`raw = 4/15 = 0.2667`.

**What matters about this example:** the level stays `WEAK` from beginning to end
- which is the truth - but the `score` **does move** (0.000 -> 0.400 -> 0.267)
and `total_attempts` reaches 5. With a run, row 5 would have said `streak = 0`
and row 4 `streak = 1`, indistinguishable from "nothing was saved". Here it is
perfectly distinguishable: there are 5 recorded attempts, there was an
improvement and then a relapse, and all of that is queryable.

### 3.1 Continuation: the recovery

Let us follow the same objective to see it climb.

Isolated hits keep adding up, one per day. The window fills up on row 8 (8
attempts) and from there on it shifts from the tail.

| # | Date | Result | Window (old->new) | Hits/Total | `raw` | `score` | **Level** | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 2026-01-06 | right | `[F,F,F,C,F,C]` | 10 / 21 | 0.476 | 0.476 | `WEAK` | still below 0.60 |
| 7 | 2026-01-07 | right | `[F,F,F,C,F,C,C]` | 17 / 28 | 0.607 | 0.607 | `LEARNING` | crosses 0.60 |
| 8 | 2026-01-08 | right | `[F,F,F,C,F,C,C,C]` | 25 / 36 | 0.694 | 0.694 | `LEARNING` | window full (8) |
| 9 | 2026-01-09 | right | `[F,F,C,F,C,C,C,C]` | 29 / 36 | 0.806 | 0.806 | `LEARNING` | the oldest `F` leaves |
| 10 | 2026-01-10 | right | `[F,C,F,C,C,C,C,C]` | 32 / 36 | 0.889 | 0.889 | `COMPETENT` | crosses 0.85 |
| 11 | 2026-01-11 | right | `[C,F,C,C,C,C,C,C]` | 34 / 36 | 0.944 | 0.944 | `COMPETENT` | `raw < 0.95`, not `MASTERED` yet |
| 12 | 2026-01-12 | right | `[F,C,C,C,C,C,C,C]` | 35 / 36 | 0.972 | 0.972 | **`MASTERED`** | `raw >= 0.95` ok - span 01-01->01-12 = 11 d >= 7 ok - 12 distinct days >= 2 ok |
| 13 | 2026-01-13 | right | `[C,C,C,C,C,C,C,C]` | 36 / 36 | 1.000 | 1.000 | **`MASTERED`** | perfect window |

Check of row 12: the only miss is in the oldest position, with weight `1`; the
hits add up to `2+3+4+5+6+7+8 = 35` over `36`. `raw = 0.9722`. It is exactly the
case that motivates the `0.95` threshold of section 2.4: with `raw == 1.0` one
more day would have been needed.

**Note how much more demanding climbing is with a window of 8.** It took 7
consecutive hits to go from `WEAK` to `COMPETENT`, and 9 for `MASTERED`. With a
window of 5, 3 and 5 were enough. That is exactly what was wanted: that the
level does not move with a single answer.

And the effect of forgetting, without a single new attempt:

Starting from row 13 (`raw = 1.000`, last attempt 2026-01-13):

| Query `as_of` | `gap` | `retention` | `score` | **Level** |
| --- | --- | --- | --- | --- |
| 2026-01-13 | 0 d | 1.000 | 1.000 | `MASTERED` |
| 2026-01-20 | 7 d | 0.948 | 0.948 | `MASTERED` |
| 2026-02-03 | 21 d | 0.851 | 0.851 | `MASTERED` |
| 2026-02-04 | 22 d | 0.844 | 0.844 | `LEARNING` |
| 2026-02-12 | 30 d | 0.794 | 0.794 | `LEARNING` |
| 2026-03-14 | 60 d | 0.630 | 0.630 | `LEARNING` |
| 2026-04-13 | 90 d | 0.500 | 0.500 | `WEAK` |
| 2026-07-12 | 180 d | 0.400 | 0.400 | `WEAK` (floor) |
| 2027-01-13 | 365 d | 0.400 | 0.400 | `WEAK` (floor) |

Note that `MASTERED` **is lost** through inactivity without recording a single
new attempt: the level is a function of the query date, not a permanent stamp.
But the descent **stops at 0.400**: a year later the engine still tells this
topic (mastered and abandoned) apart from one that was never known. Forgetting
degrades it to `WEAK`, it does not erase it.

### 3.2 General rule of the evolution

- A **hit** enters the window with the maximum weight and pushes the `score`
  upwards; it evicts the oldest attempt of the window from the tail.
- A **miss** does the same downwards. A miss does not erase the history nor
  reset anything: it lowers the `score` in proportion to its weight.
- The passage of time without attempts **only lowers** the `score`, never raises
  it, and never below `raw x 0.40`.
- **Nothing is irreversible.** Eight consecutive hits always recover
  `raw = 1.0`, whatever the past, because the window only looks at 8.
- **Recording an attempt sets the `gap` to 0** and therefore `retention = 1.0`.
  Answering a single question, even getting it wrong, stops the decay dead: the
  objective is valued again by what is known, not by how long it has gone
  untouched.

### 3.3 The "isolated question" case

**The engine does not require exams.** A single answer to a single question is a
complete, valid and sufficient `Attempt`. There is no concept of a "minimum
session", nor of a quiz that has to be completed, nor of attempts that must be
grouped: `kind` is informational and changes no computation.

This is deliberate, because that is how the user studies: questions parcelled out
over weeks, not full mock exams. Two consequences worth keeping in mind:

1. **An isolated answer moves the level very little** - that is the reason for
   the window of 8. Several consistent answers are needed to change level, which
   is the operational definition of "sustained evidence".
2. **An isolated answer stops the decay completely.** Since `retention` depends
   only on `last_attempt_at`, an isolated attempt resets the `gap` to 0. A topic
   touched yesterday is valued at 100% of its `raw`, even if the previous
   attempt was three months ago.

From those two effects follows the right reading: **answering an isolated
question keeps a topic alive, but does not promote it.** Going up a level demands
volume; not going down only demands consistency.

---

## 4. Next review

Spaced repetition with fixed intervals. It is computed, like everything else,
from the history: **there is no stored `ease` or `interval` that can get
corrupted** (section 8, failure 3).

### 4.1 The ladder

`SCHEDULE_DAYS = [1, 3, 7, 14, 30]`

(The `30` here is days of the review ladder and bears no relation to
`DECAY_HALF_LIFE_DAYS = 90`, which governs forgetting. They are two different
mechanisms.)

### 4.2 Rule

1. Let `S` be the **run of consecutive hits at the end** of the sorted list of
   attempts (counting from the most recent backwards until the first miss).
   *This is used exclusively to pick the review interval, and never as a measure
   of progress.*
2. If `S == 0` (the last attempt was a miss) implies `index = 0` implies
   **1 day**.
3. If `S >= 1` implies `index = min(S - 1, len(SCHEDULE_DAYS) - 1)`.
   - `S=1` -> 1 day - `S=2` -> 3 days - `S=3` -> 7 days - `S=4` -> 14 days -
     `S>=5` -> 30 days.
4. `next_review_at = last_attempt_at + index_of_days`.
5. If the objective reaches `MASTERED`, the interval is multiplied by `2`
   (ceiling: 60 days).
6. If there are no attempts: `next_review_at = None` and `is_due = False`. An
   objective with no evidence is not "due", it is **unstarted**; they are listed
   separately (section 5.2).

### 4.3 Due state

`is_due(as_of) == (next_review_at is not None and next_review_at <= as_of)`.

Applied to the example of section 3: after row 5 (the miss of 2026-01-05),
`S=0`, so `next_review_at = 2026-01-06`. After row 13 (2026-01-13), `S=8` and
level `MASTERED`, so `30 x 2 = 60` days -> `2026-03-14`.

---

## 5. Queries

### 5.1 State at a date - the time guarantee

`get_state(objective_id, as_of)` returns the `ObjectiveState` computed
**ignoring completely every attempt with `at > as_of`**.

Guarantees:

- **Historical reproducibility.** Querying with `as_of = 2026-01-04` gives today
  exactly what it will give a year from now, even if a hundred new attempts have
  been recorded in the meantime. The past does not change.
- **Insensitivity to write order.** Recording the attempts in any order produces
  the same historical states, because the cut is by `at`, never by insertion
  order nor by `recorded_at`.
- **It answers the user's question.** "Was I better two weeks ago?" is answered
  by comparing `get_state(o, today).score` with
  `get_state(o, today - 14d).score`, or directly with `compare_states`.

This is possible **only** because the history is append-only and the level is
recomputed. It is the structural reason for decision 1 of section 0.

### 5.2 What is due for review

`get_due(profile_id, as_of, ...)` returns the objectives with `is_due == True`
at that date, sorted by urgency: the most overdue first (larger
`as_of - next_review_at`); on a tie, the lowest `score` first; on a tie,
ascending `objective_id` (total determinism).

Objectives **without attempts** do not appear here. They are obtained with
`get_unstarted`, because "I have never seen it" and "it is due for review" are
different things and mixing them hides the uncovered material.

### 5.3 Time series

`get_timeline(objective_id, start, end, step)` returns a list of
`ObjectiveState`, one per date of the grid. It is `get_state` applied in a loop;
it exists so that the evolution can be plotted without the UI reimplementing the
cut.

---

## 6. Invariants of the engine

Any implementation must satisfy them. They are verifiable from the outside.

| # | Invariant |
| --- | --- |
| **I1** | **Append-only.** No operation of the public API modifies or deletes an already recorded `Attempt`. There is no `update_attempt` nor `delete_attempt`. |
| **I2** | **Absence of an internal clock.** No function in `core/` calls `datetime.now()`, `date.today()`, `time.time()` or equivalents. Time arrives as a parameter or through a `Clock`. It is verifiable with a grep over `core/`. |
| **I3** | **Determinism.** `get_state(o, t)` with the same set of attempts always returns the same thing, in any process, platform or insertion order. |
| **I4** | **Full derivation.** Every field of `ObjectiveState` is a pure function of (attempts, `as_of`). Nothing is read from a persisted aggregate. |
| **I5** | **Monotonicity of the cut.** If `t1 <= t2`, then the set of attempts considered at `t1` is a subset of that of `t2`. (The level is **not** monotone; the set is.) |
| **I6** | **Rebuild.** Deleting any cache or index and recomputing from the attempts produces an identical state. Corollary: a corrupt aggregate is always fixed by recomputing. |
| **I7** | **Isolation between profiles.** The attempts of one profile do not affect any state of another profile. |
| **I8** | **Verifiable recording.** Recording an attempt returns the persisted `Attempt` with its `attempt_id`; if the write fails, an exception is raised. **It never fails silently.** |
| **I9** | **Consistency by count.** The consistency check compares **counts and sums**, not set membership (section 8, failure 2). |
| **I10** | **No run field in the state.** `ObjectiveState` does not expose `streak`. The run exists only as a local variable of the review computation (section 4.2). |

---

## 7. Edge cases

Expected answer, with no ambiguity. Whoever tests can write these cases
directly.

### C1 - Objective without attempts
`level = UNASSESSED`, `score = 0.0`, `total_attempts = 0`,
`recent_window = ()`, `first_attempt_at = last_attempt_at = None`,
`next_review_at = None`, `is_due = False`.
It does not appear in `get_due`. It does appear in `get_unstarted`.
**It is not an error**: no exception is raised for querying an objective without
attempts. One is raised (`UnknownObjectiveError`) if the objective does not
exist in the profile.

### C2 - A single attempt
`level = UNASSESSED` (`n < MIN_ATTEMPTS`) and `score = 0.0`, **whether it is a
hit or a miss**. But `total_attempts = 1`, `recent_window = (True,)` or
`(False,)`, and `next_review_at` **is** computed (section 4). That is: the
attempt is recorded and visible, it simply is not enough to assign a level.

### C3 - Two attempts on the same day
They count as **two independent attempts**. They are not collapsed, they are not
averaged. Both enter the window with different weights according to their
temporal order. It is the normal case when several isolated questions are
answered in a row.
For `distinct_days` they count as **a single day** (calendar dates are compared,
not instants) - which affects the promotion to `MASTERED`. "Same day" is the
**same UTC date** of the instant `at`, not the date in the zone each attempt was
recorded with: two attempts at `23:00-05:00` and `04:30+00:00` of the same UTC
day are a single day.
If they have the **exact same `at`**, they are sorted by ascending
`attempt_id`.

### C4 - Attempts inserted out of chronological order
Recording the attempt of day 3 **after** the attempt of day 5 is legal and does
not raise an error. The engine always sorts by `at`, not by arrival order.
Mandatory consequence: after the late insertion, `get_state(o, day_4)` starts
including that attempt and **may return a level different from the one it
returned before**. This is correct: information about the past was added, the
past was not altered. `recorded_at` leaves evidence of the late insertion.

### C5 - Long gap without activity
The decay **has a floor**: `retention` never drops below `RETENTION_FLOOR`
(0.40), and therefore `score` never drops below `raw x 0.40`. An objective with
`raw = 1.0` and a 90 day gap has `retention = 0.500` implies `score = 0.500`
implies `WEAK`; with 365 days it has `retention = 0.400` implies
`score = 0.400`, and there it stays however much time passes.

The floor is what prevents "abandoned" and "never learned" from collapsing onto
the same number (section 2.2 step 5).
`next_review_at` ends up far in the past, so `is_due = True` and it appears
first in `get_due` for being the most overdue. **The engine never "forgets" the
objective nor archives it on its own.**

### C6 - Query with an `as_of` before the first attempt
Equivalent to C1: the objective had no evidence yet at that date.
`level = UNASSESSED`. It is not an error.

### C7 - Query with an `as_of` in the future
Legal. Every attempt is included and the decay is computed with that future
`gap`. It serves to answer "how rusty will I be on the day of the exam?".

### C8 - Attempt on a nonexistent `objective_id`
`record_attempt` raises `UnknownObjectiveError`. **The objective is not
auto-created**: a misspelled id must fail loudly, not conjure a phantom
objective.

### C9 - Duplicate `attempt_id`
`record_attempt` raises `DuplicateAttemptError`. It guarantees detectable
idempotency and protects I1: retrying a write does not duplicate evidence.

### C10 - Exact tie at the threshold
`score == 0.85` implies `COMPETENT`. `score == 0.60` implies `LEARNING`. The
comparison is `>=`. To avoid floating point surprises, the `score` is **rounded
to 6 decimals** before applying the thresholds.

---

## 8. How this design avoids the known failures

The five failures diagnosed in the earlier systems, and the structural property
that makes them impossible here.

### Failure 1 - Confusing a run with progress

> *An objective with 5 answers showed `streak=1` and it looked like nothing was
> being saved.*

**What prevents it:** `ObjectiveState` **has no `streak` field** (I10). Progress
is expressed with three things a run cannot give: a continuous `score` weighted
by recency, `total_attempts` / `correct_attempts` which only grow, and
`recent_window` which literally shows the sequence. In the example of section 3,
row 5 shows `total_attempts=5`, `recent_window=(F,F,F,C,F)` and `score=0.267`:
it is impossible to confuse with "nothing was saved".

The run survives only as a local variable of the review interval computation
(section 4.2), where it is the right semantics, and the spec says explicitly
that it must not be used as a measure of progress.

### Failure 2 - A verifier that compares sets instead of counts

> *It printed "OK - consistent" over a corrupt state.*

**What prevents it:** `check_consistency` (section 9.5) has an explicit contract
to compare **counts and sums**, not membership (I9), and returns a
`ConsistencyReport` with the numbers from both sides, not a boolean or a string.
A report that says `store=7, recomputed=5` cannot print "OK". On top of that,
`ConsistencyReport.ok` is defined as *every count matches*, not as *I found no
discrepancies*. The absence of evidence of an error is not `ok = True`.

### Failure 3 - Cumulative counters, corrupted and irreversible

> *`lapses` and `ease` got corrupted and could not be reverted.*

**What prevents it:** **there are no cumulative counters.** There is no `ease`,
no `lapses`, no stored `interval`. The review interval is derived from the
trailing run, and the run is derived from the history (section 4). By I6, any
corruption of an aggregate or cache is fixed by deleting it and recomputing; the
only unrecoverable data would be a lost attempt, and attempts are append-only
and immutable (I1).

### Failure 4 - Nothing forced recording; it failed silently

> *It depended on an LLM remembering to run a command.*

**What prevents it, in three layers:**

1. **I8:** `record_attempt` returns the persisted `Attempt` or raises an
   exception. There is no "I did nothing and returned None" path.
2. **Silence detection:** `get_stale` (section 9.4) lists the objectives with no
   attempts for more than `n` days, and `get_unstarted` those that never had
   one. A frozen state stops being invisible: it shows up in a list.
3. **`SessionRecorder` (section 9.6):** a session context that demands closing
   while declaring how many attempts were recorded. If it closes with zero, it
   marks the session as `EMPTY` instead of ending in silence. Recording
   discipline stops depending on the memory of whoever operates it.

The spec cannot force anyone to run a command, but it can make **not running it
visible**. That is what these three layers do.

### Failure 5 - Non-injectable dates

> *Impossible to test the temporal evolution.*

**What prevents it:** I2. `core/` has no access to the clock: every function
receives an explicit `as_of` or an injected `Clock`. `FixedClock` allows pinning
the date in a test and `OffsetClock` moving it forward. A bot can simulate six
months of study in milliseconds, which is exactly what the requirement of the
deliberate series "wrong, wrong, wrong, right, wrong" asks for.

---

## 9. Surface of the API

The exact names, types and docstrings live in `core/`. This is the map.

### 9.1 Injectable abstractions (`core/clock.py`, `core/storage.py`)

| Name | What it is |
| --- | --- |
| `Clock` (Protocol) | `now() -> datetime`. The only door to real time. |
| `FixedClock` | Always returns the same date. For tests. |
| `OffsetClock` | A base `Clock` plus a shift. To simulate moving forward. |
| `SystemClock` | The real clock. **It lives in `store/`, not in `core/`**, so that I2 is verifiable with a grep over `core/`. |
| `AttemptStore` (Protocol) | Persistence of attempts: `append(profile_id, attempt)`, `list_for_objective`, `list_all`, `count`, `exists`. It only appends and reads. `profile_id` travels in the call and not in `Attempt` (section 1.3 does not include it): the store indexes by profile, exactly as in `list_for_objective`, `list_all` and `count`; `attempt_id` is globally unique (C9). |
| `ProfileStore` (Protocol) | Persistence of profiles and objectives. |

### 9.2 Model (`core/models.py`)

`Profile`, `Objective`, `Attempt`, `AttemptKind`, `Level`, `ObjectiveState`,
`ProfileSummary`, `StateComparison`, `ConsistencyReport`, `SessionReport`. All
of them are frozen *dataclasses* (`frozen=True`): immutable by construction.

### 9.3 Pure computation (`core/leveling.py`, `core/scheduling.py`)

| Function | What it does |
| --- | --- |
| `compute_score(attempts, as_of)` | Steps 1-5 of section 2.2, with the retention floor. |
| `compute_level(score, attempts, as_of)` | Steps 6-7 of section 2.2. |
| `compute_state(objective_id, attempts, as_of)` | The complete `ObjectiveState`. |
| `compute_next_review(attempts, level)` | Section 4. |
| `trailing_success_run(attempts)` | The trailing run. Internal use of scheduling. |

They are pure functions over lists of `Attempt`. They touch neither the store
nor the clock.

### 9.4 Engine (`core/tracker.py` - class `LearningTracker`)

| Method | What it does |
| --- | --- |
| `record_attempt(...)` | Records an attempt with an injected date. Returns the `Attempt`. |
| `record_series(objective_id, results, start, step, kind)` | Records a series of results on spaced dates. A shortcut for the verification bot and the tests; it reproduces section 3. Returns the list of `Attempt`. |
| `get_level(objective_id, as_of=None)` | The `Level` of an objective at a date. |
| `get_state(objective_id, as_of=None)` | The complete `ObjectiveState`. |
| `get_state_at(objective_id, as_of)` | The same, with a mandatory `as_of`. An explicit historical query. |
| `get_all_states(as_of=None)` | The state of every objective of the profile, by `objective_id`. |
| `get_due(as_of=None, limit=None)` | What is due for review (section 5.2). |
| `get_unstarted(as_of=None)` | Objectives without a single attempt. |
| `get_stale(as_of=None, days=14)` | Objectives with no recent activity (failure 4). |
| `get_timeline(objective_id, start, end, step)` | Time series of states. |
| `compare_states(objective_id, earlier, later)` | "Was I better two weeks ago?" |
| `get_summary(as_of=None)` | Profile aggregate: split by level, coverage. |
| `get_profile()` | The `Profile` this tracker operates on. |
| `check_consistency(as_of=None)` | Section 8, failure 2. Returns a `ConsistencyReport`. |
| `rebuild(as_of=None)` | I6. There is no cache to delete: it recomputes the state of every objective and returns how many it recomputed. |
| `session(...)` | Opens a `SessionRecorder`. |
| `profile_id` (property) | Profile this tracker operates on. |
| `clock` (property) | The injected clock, read only, exposed for collaborators such as `SessionRecorder`. It is still I2: the `Clock` was chosen by whoever built the tracker. |

`as_of=None` means "use `clock.now()`". It is the only concession, and it is
still injected time: the `Clock` is chosen by whoever builds the tracker.

### 9.5 `ConsistencyReport`

Fields: `ok`, `checks` (a list of `ConsistencyCheck` with `name`, `expected`,
`actual`, `passed`), `objectives_checked`. `ok` is `True` only if **every** check
passed and at least one objective was checked.

### 9.6 `SessionRecorder` (`core/session.py`)

A context manager. It accumulates attempts and on close produces a
`SessionReport` with `attempts_recorded`, `objectives_touched` and `status`
(`RECORDED` or `EMPTY`). Closing a session with no attempts is an explicit and
visible result, not a non-event.

---

## 10. What is deliberately NOT in v1

So that whoever implements does not invent extras:

- `confidence` and `weight` are stored but **do not affect** any computation.
- There are no dependencies between objectives (prerequisites).
- There is no per-item difficulty nor an SM-2 style model with a variable
  `ease` - that is exactly failure 3.
- There is no deletion or editing of attempts.
- Multi-profile: the model supports it (isolated profiles, I7) but one
  `LearningTracker` operates on **one** profile.

---

## 11. Language of the project

The code, the documentation, this contract and the commit messages are in
English. What the CLI prints to the user - command output and the text of
exception messages - is in Spanish, and the tests assert it as such.

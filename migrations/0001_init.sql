-- Schema for the learning-tracker module.
--
-- One schema per module: this Postgres server is shared with other products,
-- so every table of this project lives under __SCHEMA__ (a placeholder the
-- runner replaces with the real schema name, "learning" in production).

-- Every identifier column carries COLLATE "C" on purpose. Postgres orders
-- text under the database collation, which on a typical en_US.utf8 cluster
-- ignores case and punctuation at the primary level; Python orders strings by
-- codepoint. The same attempts would come back in a different order from this
-- backend than from the memory and JSON ones, and since the engine weights the
-- recent window by position, a different order is a different score and can be
-- a different level. Worse, the order would depend on the locale the cluster
-- happened to be created with, so a laptop and a deployment could disagree in
-- silence (SPEC C3, C4, I3).
--
-- COLLATE "C" is byte order, and UTF-8 byte order is codepoint order, so it
-- reproduces Python's comparison exactly rather than approximately. It sits on
-- the columns, not in the ORDER BY, so the indexes can still satisfy the sort.

CREATE SCHEMA IF NOT EXISTS __SCHEMA__;

CREATE TABLE __SCHEMA__.profiles (
    profile_id text COLLATE "C" PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE __SCHEMA__.objectives (
    profile_id text COLLATE "C" NOT NULL REFERENCES __SCHEMA__.profiles (profile_id) ON DELETE CASCADE,
    objective_id text COLLATE "C" NOT NULL,
    title text NOT NULL,
    domain text,
    weight double precision NOT NULL DEFAULT 1.0,
    tags text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (profile_id, objective_id)
);

-- attempt_id is the ONLY primary key: it is globally unique across profiles
-- (SPEC C9), never composite with profile_id (guarantee 3 of ACU-247). The
-- table has no update/delete privileges to worry about: the application layer
-- (PostgresAttemptStore) simply never issues them (SPEC I1).
CREATE TABLE __SCHEMA__.attempts (
    attempt_id text COLLATE "C" PRIMARY KEY,
    profile_id text COLLATE "C" NOT NULL,
    objective_id text COLLATE "C" NOT NULL,
    at timestamptz NOT NULL,
    correct boolean NOT NULL,
    kind text NOT NULL,
    confidence double precision,
    note text,
    recorded_at timestamptz
);

-- Speeds up the reads the store actually performs: cut by "at", ordered by
-- "at" then "attempt_id" (SPEC C4), scoped by profile and objective.
CREATE INDEX attempts_profile_objective_at_idx
    ON __SCHEMA__.attempts (profile_id, objective_id, at, attempt_id);

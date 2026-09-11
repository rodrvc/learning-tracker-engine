-- Schema for the learning-tracker module.
--
-- One schema per module: this Postgres server is shared with other products,
-- so every table of this project lives under __SCHEMA__ (a placeholder the
-- runner replaces with the real schema name, "learning" in production).

CREATE SCHEMA IF NOT EXISTS __SCHEMA__;

CREATE TABLE __SCHEMA__.profiles (
    profile_id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE __SCHEMA__.objectives (
    profile_id text NOT NULL REFERENCES __SCHEMA__.profiles (profile_id) ON DELETE CASCADE,
    objective_id text NOT NULL,
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
    attempt_id text PRIMARY KEY,
    profile_id text NOT NULL,
    objective_id text NOT NULL,
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

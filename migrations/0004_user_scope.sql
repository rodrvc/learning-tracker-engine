-- Per-user data (issue #58): the "who studies it" axis.
--
-- Until now profile_id carried two meanings at once, what is being studied and
-- whoever studies it, so a valid session still read one shared dataset. This
-- adds user_id to every table that holds a user's data and makes it part of
-- each key that used to be scoped by profile alone.
--
-- user_id is the Clerk session's `sub`. The default 'local' is the one implicit
-- user of a deployment with authentication off (and of the CLI and the tests):
-- every row that exists today is backfilled to it by ADD COLUMN, which is what
-- it was, a single user's data. The default is kept (not dropped) so a writer
-- that predates this migration keeps landing in that same implicit namespace;
-- the stores always pass user_id explicitly.
--
-- Global keys that stay global on purpose: attempt_id, material_id and
-- question_id remain the sole primary keys of their tables (SPEC C9), so an id
-- is unique across users and a lookup by id is always followed by a user_id
-- filter in the stores, never trusted on its own.

ALTER TABLE __SCHEMA__.objectives DROP CONSTRAINT objectives_profile_id_fkey;
ALTER TABLE __SCHEMA__.objectives DROP CONSTRAINT objectives_pkey;
ALTER TABLE __SCHEMA__.profiles DROP CONSTRAINT profiles_pkey;

ALTER TABLE __SCHEMA__.profiles   ADD COLUMN user_id text COLLATE "C" NOT NULL DEFAULT 'local';
ALTER TABLE __SCHEMA__.objectives ADD COLUMN user_id text COLLATE "C" NOT NULL DEFAULT 'local';
ALTER TABLE __SCHEMA__.attempts   ADD COLUMN user_id text COLLATE "C" NOT NULL DEFAULT 'local';
ALTER TABLE __SCHEMA__.materials  ADD COLUMN user_id text COLLATE "C" NOT NULL DEFAULT 'local';
ALTER TABLE __SCHEMA__.questions  ADD COLUMN user_id text COLLATE "C" NOT NULL DEFAULT 'local';

ALTER TABLE __SCHEMA__.profiles ADD PRIMARY KEY (user_id, profile_id);
ALTER TABLE __SCHEMA__.objectives ADD PRIMARY KEY (user_id, profile_id, objective_id);
ALTER TABLE __SCHEMA__.objectives
    ADD CONSTRAINT objectives_profile_fkey
    FOREIGN KEY (user_id, profile_id)
    REFERENCES __SCHEMA__.profiles (user_id, profile_id) ON DELETE CASCADE;

-- Indexes: same reads as before, now led by user_id.
DROP INDEX __SCHEMA__.profiles_active_idx;
CREATE INDEX profiles_active_idx
    ON __SCHEMA__.profiles (user_id, profile_id)
    WHERE NOT archived;

DROP INDEX __SCHEMA__.attempts_profile_objective_at_idx;
CREATE INDEX attempts_user_profile_objective_at_idx
    ON __SCHEMA__.attempts (user_id, profile_id, objective_id, at, attempt_id);

DROP INDEX __SCHEMA__.materials_topic_created_idx;
CREATE INDEX materials_user_topic_created_idx
    ON __SCHEMA__.materials (user_id, topic_id, created_at, material_id);

DROP INDEX __SCHEMA__.questions_topic_created_idx;
DROP INDEX __SCHEMA__.questions_objective_created_idx;
CREATE INDEX questions_user_topic_created_idx
    ON __SCHEMA__.questions (user_id, topic_id, created_at, question_id);
CREATE INDEX questions_user_objective_created_idx
    ON __SCHEMA__.questions (user_id, objective_id, created_at, question_id);

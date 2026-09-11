-- Study material and generated questions (ACU-245 / ACU-259). Same schema as
-- the engine's tables (__SCHEMA__, replaced by the runner): the engine does
-- not know this content exists, but both share the "learning" schema in
-- production because they are the same product.

-- Every identifier column carries COLLATE "C" for the same reason as in
-- 0001_init.sql: Postgres orders text under the database collation, Python
-- orders strings by codepoint, and content/storage.py promises the same
-- canonical order regardless of backend. See 0001_init.sql for the full
-- explanation.

CREATE TABLE __SCHEMA__.materials (
    material_id text COLLATE "C" PRIMARY KEY,
    topic_id text COLLATE "C" NOT NULL,
    title text NOT NULL,
    source text NOT NULL,
    body text NOT NULL,
    created_at timestamptz NOT NULL
);

-- Speeds up list_for_topic's canonical order: created_at, then material_id.
CREATE INDEX materials_topic_created_idx
    ON __SCHEMA__.materials (topic_id, created_at, material_id);

-- options is a JSON array of [key, text] pairs. JSON preserves array element
-- order (unlike object key order, which is not part of the content contract
-- here), which is what lets this column round-trip Question.options exactly
-- as given: the order is what a reader sees, so it must survive a store/read
-- cycle unchanged.
CREATE TABLE __SCHEMA__.questions (
    question_id text COLLATE "C" PRIMARY KEY,
    topic_id text COLLATE "C" NOT NULL,
    objective_id text COLLATE "C" NOT NULL,
    stem text NOT NULL,
    options jsonb NOT NULL,
    correct_key text NOT NULL,
    explanation text NOT NULL,
    material_id text COLLATE "C" NOT NULL
        REFERENCES __SCHEMA__.materials (material_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL
);

-- Speeds up list_for_topic and list_for_objective's canonical order, and the
-- delete half of replace_for_material.
CREATE INDEX questions_topic_created_idx
    ON __SCHEMA__.questions (topic_id, created_at, question_id);
CREATE INDEX questions_objective_created_idx
    ON __SCHEMA__.questions (objective_id, created_at, question_id);
CREATE INDEX questions_material_idx
    ON __SCHEMA__.questions (material_id);

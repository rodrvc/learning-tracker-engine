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
    created_at timestamptz NOT NULL,
    -- Lets questions below carry a composite foreign key that enforces
    -- Question.topic_id == its material's topic_id structurally (see
    -- questions_material_topic_fkey). material_id alone is already unique
    -- via the primary key; this constraint only makes the pair referenceable.
    CONSTRAINT materials_material_topic_key UNIQUE (material_id, topic_id)
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
    material_id text COLLATE "C" NOT NULL,
    created_at timestamptz NOT NULL,

    -- Ownership (content/storage.py's QuestionStore docstring): material_id
    -- must name a material that already exists. Plain REFERENCES, no ON
    -- DELETE CASCADE - MaterialStore is append-only by the deliberate
    -- absence of a delete method, so CASCADE would encode a deletion the
    -- contract says cannot happen. A stray manual delete against this
    -- schema is refused loudly instead of silently taking the questions
    -- with it, the same way TRUNCATE ... CASCADE in the test harness still
    -- empties both tables without depending on this foreign key's action.
    CONSTRAINT questions_material_id_fkey
        FOREIGN KEY (material_id) REFERENCES __SCHEMA__.materials (material_id),

    -- Topical consistency (content/storage.py's QuestionStore docstring): a
    -- question's topic_id must equal its material's. Enforced structurally
    -- rather than in application code, so it cannot drift the way an
    -- unchecked second source of truth would. Named separately from the
    -- foreign key above so content/postgres.py can tell the two failure
    -- modes apart by constraint name and map each to the same exception the
    -- memory backend raises for it (UnknownMaterialError for a missing
    -- material, InvalidQuestionError for a topic mismatch).
    CONSTRAINT questions_material_topic_fkey
        FOREIGN KEY (material_id, topic_id)
        REFERENCES __SCHEMA__.materials (material_id, topic_id)
);

-- Speeds up list_for_topic and list_for_objective's canonical order, and the
-- delete half of replace_for_material.
CREATE INDEX questions_topic_created_idx
    ON __SCHEMA__.questions (topic_id, created_at, question_id);
CREATE INDEX questions_objective_created_idx
    ON __SCHEMA__.questions (objective_id, created_at, question_id);
CREATE INDEX questions_material_idx
    ON __SCHEMA__.questions (material_id);

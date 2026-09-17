-- Archiving a topic (issue #47): the flag that takes a profile out of the
-- default listing without taking anything away from it.
--
-- A column on profiles and not a DELETE, because a topic that is no longer
-- being studied still owns its attempts, and attempts are append-only (SPEC
-- I1): the row has to survive whoever stops looking at it. Note as well that
-- this table cascades to objectives, so a delete would silently take the
-- catalog with it.

-- NOT NULL DEFAULT false, so every profile that already exists is read as
-- being studied, which is what it was. A nullable column would have made
-- "never archived" and "unknown" two different states in the data for no gain,
-- and every reader would have had to collapse them back anyway.
ALTER TABLE __SCHEMA__.profiles
    ADD COLUMN archived boolean NOT NULL DEFAULT false;

-- Partial index, not a plain one: the query this exists for is "the topics
-- being studied", the archive is read rarely and by hand, and the column is
-- false for almost every row. An index over the whole table would be ignored
-- for exactly the lookup it was meant to serve.
CREATE INDEX profiles_active_idx
    ON __SCHEMA__.profiles (profile_id)
    WHERE NOT archived;

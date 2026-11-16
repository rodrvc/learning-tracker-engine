-- Organization membership (issue #75): who belongs to an organization, as far as
-- this service has seen.
--
-- Clerk is the source of truth for membership; this service only ever learns of
-- it through a verified session token that carries an active organization. So
-- the table is a record of sightings, upserted whenever such a token is used:
-- a member who has never opened the application is not here, and one who left
-- the organization stays until someone cleans it up. That is enough for a
-- teacher to list the people who have actually used the product, which is all
-- the read-only teacher view needs. Role is the one the token carried last
-- (always the full "org:" key).
CREATE TABLE __SCHEMA__.org_members (
    org_id text COLLATE "C" NOT NULL,
    user_id text COLLATE "C" NOT NULL,
    role text NOT NULL,
    display_name text,
    email text,
    last_seen timestamptz NOT NULL,
    PRIMARY KEY (org_id, user_id)
);

ALTER TABLE links
    ALTER COLUMN campaign_id TYPE TEXT USING campaign_id::text,
    ALTER COLUMN creator_id TYPE TEXT USING creator_id::text,
    ADD CONSTRAINT links_campaign_id_format CHECK (campaign_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    ADD CONSTRAINT links_creator_id_format CHECK (creator_id ~ '^[A-Za-z0-9_-]{1,64}$');

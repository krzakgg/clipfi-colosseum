CREATE TABLE links (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE CHECK (code ~ '^[A-Za-z0-9_-]{4,64}$'),
    campaign_id  UUID NOT NULL,
    creator_id   UUID NOT NULL,
    target_url   TEXT NOT NULL CHECK (length(target_url) <= 2048),
    platform     TEXT CHECK (platform ~ '^[a-z0-9_]{1,32}$'),
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at    TIMESTAMPTZ,
    ends_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at)
);

CREATE INDEX links_campaign_idx ON links (campaign_id);
CREATE INDEX links_creator_idx ON links (creator_id);

-- source of truth for payouts
CREATE TABLE click_buckets (
    link_id        BIGINT NOT NULL REFERENCES links (id),
    bucket_start   TIMESTAMPTZ NOT NULL,
    raw_clicks     INTEGER NOT NULL CHECK (raw_clicks >= 0),
    unique_clicks  INTEGER NOT NULL CHECK (unique_clicks >= 0),
    PRIMARY KEY (link_id, bucket_start)
);

-- id is the Redis stream entry id
CREATE TABLE click_events (
    id            TEXT PRIMARY KEY,
    link_id       BIGINT NOT NULL REFERENCES links (id),
    occurred_at   TIMESTAMPTZ NOT NULL,
    is_unique     BOOLEAN NOT NULL,
    visitor_hash  TEXT NOT NULL,
    referer_host  TEXT
);

CREATE INDEX click_events_link_time_idx ON click_events (link_id, occurred_at);
CREATE INDEX click_events_time_idx ON click_events (occurred_at);

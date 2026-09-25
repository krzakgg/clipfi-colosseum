-- The role is created by deploy/postgres-init (it needs a password).
-- Without it, e.g. in local development, this is a no-op.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tracking_app') THEN
        GRANT SELECT, INSERT, UPDATE ON links TO tracking_app;
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO tracking_app', pg_get_serial_sequence('links', 'id'));
        GRANT SELECT, INSERT, UPDATE ON click_buckets TO tracking_app;
        GRANT SELECT, INSERT, DELETE ON click_events TO tracking_app;
    END IF;
END
$$;

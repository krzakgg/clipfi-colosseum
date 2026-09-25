#!/bin/sh
# Sourced by the postgres entrypoint unless executable, so no `set` here.
# Table privileges are granted by migration 0002.
: "${TRACKING_APP_DB_PASSWORD:?set TRACKING_APP_DB_PASSWORD in .env}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_password="$TRACKING_APP_DB_PASSWORD" -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE tracking_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"db" TO tracking_app;
GRANT USAGE ON SCHEMA public TO tracking_app;
SQL

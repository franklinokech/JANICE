#!/bin/sh
# Runs once, when the Postgres data volume is first created: makes the
# database Dagster keeps its run history, schedules and sensor state in.
# For an existing volume, run once by hand:
#   docker compose exec db createdb -U "$POSTGRES_USER" dagster
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -c "CREATE DATABASE \"${DAGSTER_POSTGRES_DB:-dagster}\""

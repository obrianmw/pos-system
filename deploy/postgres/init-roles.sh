#!/bin/sh
# Runs once, when the database volume is first created (docker-entrypoint-initdb.d).
# Creates the limited role the app uses. The owner role ($POSTGRES_USER) builds the tables (migrations)
# and is for database administrators only; the app role can read and change rows but not the schema,
# cannot create roles or databases, and has its own password. Neither is a till/back-office login.
set -eu
: "${DB_APP_USER:?DB_APP_USER is required}"
: "${DB_APP_PASSWORD:?DB_APP_PASSWORD is required}"
if [ "$DB_APP_PASSWORD" = "$POSTGRES_PASSWORD" ]; then
  echo "DB_APP_PASSWORD must differ from DB_OWNER_PASSWORD" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="$DB_APP_USER" -v app_password="$DB_APP_PASSWORD" \
     -v owner="$POSTGRES_USER" -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app_user";
-- Tables the owner creates later (via migrations) are usable by the app for rows only.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app_user";
SQL
echo "Created limited app role $DB_APP_USER"

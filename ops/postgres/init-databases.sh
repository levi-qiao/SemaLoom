#!/usr/bin/env bash
set -euo pipefail

for database in semaloom_tax semaloom_orders semaloom_suppliers semaloom_meta; do
  psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --command "CREATE DATABASE ${database}"
done

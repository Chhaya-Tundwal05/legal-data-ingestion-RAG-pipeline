#!/bin/bash
# Post-init script to refresh collation version
# This fixes collation version mismatches that can occur when the database
# was created with a different OS library version
#
# This script runs after the database is created and schema.sql is executed

set -e

echo "Refreshing collation version for database 'dockets'..."

# Use psql to refresh the collation version
# This is safe to run multiple times
psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "dockets" <<-EOSQL
    -- Refresh collation version to match current OS libraries
    -- This fixes warnings about collation version mismatches
    ALTER DATABASE dockets REFRESH COLLATION VERSION;
EOSQL

echo "Collation version check completed."


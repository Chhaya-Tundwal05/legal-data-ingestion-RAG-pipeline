# Quick Start Guide

## Prerequisites Check

✅ Python 3.11.3 - Installed  
✅ Dependencies - Installed (psycopg2-binary, python-dotenv)  
✅ .env file - Created  
⚠️ PostgreSQL - **Needs to be installed/started**

## Install PostgreSQL (macOS)

### Option 1: Using Homebrew (Recommended)

```bash
# Install PostgreSQL
brew install postgresql@15

# Start PostgreSQL service
brew services start postgresql@15

# Add to PATH (if needed)
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Option 2: Download PostgreSQL.app

1. Download from: https://www.postgresql.org/download/macosx/
2. Install the .dmg file
3. Launch PostgreSQL.app
4. It will start the server automatically

### Option 3: Using Postgres.app

1. Download from: https://postgresapp.com/
2. Install and launch
3. Click "Initialize" to create a new server

## After PostgreSQL is Running

Once PostgreSQL is installed and running, continue with:

```bash
# 1. Create database
createdb legal_dockets
# OR if using psql:
psql -U postgres -c "CREATE DATABASE legal_dockets;"

# 2. Create schema
psql -U postgres -d legal_dockets -f schema.sql

# 3. Update .env with your PostgreSQL credentials if different
# (Default: user=postgres, password=postgres)

# 4. Run ingestion
python3 ingest.py
```

## Verify PostgreSQL is Running

```bash
# Check if PostgreSQL is running
pg_isready

# OR test connection
psql -U postgres -c "SELECT version();"
```

## Troubleshooting

### Connection Refused
- Make sure PostgreSQL service is running
- Check if port 5432 is available: `lsof -i :5432`
- Verify credentials in `.env` file

### Permission Denied
- Check PostgreSQL user permissions
- May need to create user: `createuser -s postgres`

### Database Already Exists
- Drop and recreate: `dropdb legal_dockets && createdb legal_dockets`


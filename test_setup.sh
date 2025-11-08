#!/bin/bash
# Quick setup script for testing the legal docket ingestion pipeline

set -e  # Exit on error

echo "=========================================="
echo "Legal Docket Pipeline - Test Setup"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if PostgreSQL is installed
echo -e "${YELLOW}Step 1: Checking PostgreSQL...${NC}"
if ! command -v psql &> /dev/null; then
    echo -e "${RED}PostgreSQL not found. Please install PostgreSQL first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL found${NC}"

# Check if Python is installed
echo -e "${YELLOW}Step 2: Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 not found. Please install Python 3.8+ first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python found${NC}"

# Install Python dependencies
echo -e "${YELLOW}Step 3: Installing Python dependencies...${NC}"
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check if .env file exists
echo -e "${YELLOW}Step 4: Checking environment configuration...${NC}"
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env file...${NC}"
    cat > .env << EOF
DB_HOST=localhost
DB_PORT=5432
DB_NAME=legal_dockets
DB_USER=postgres
DB_PASSWORD=postgres
JSON_FILE=raw_dockets.json
QUARANTINE_DIR=quarantine
EOF
    echo -e "${YELLOW}⚠ Please edit .env with your PostgreSQL credentials${NC}"
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# Check if database exists
echo -e "${YELLOW}Step 5: Checking database...${NC}"
DB_NAME=$(grep DB_NAME .env | cut -d '=' -f2 | tr -d ' ')
DB_USER=$(grep DB_USER .env | cut -d '=' -f2 | tr -d ' ')

if psql -U "$DB_USER" -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo -e "${GREEN}✓ Database '$DB_NAME' exists${NC}"
    read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Dropping database...${NC}"
        psql -U "$DB_USER" -c "DROP DATABASE IF EXISTS $DB_NAME;"
        echo -e "${YELLOW}Creating database...${NC}"
        psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;"
        echo -e "${GREEN}✓ Database recreated${NC}"
    fi
else
    echo -e "${YELLOW}Creating database...${NC}"
    psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;"
    echo -e "${GREEN}✓ Database created${NC}"
fi

# Create schema
echo -e "${YELLOW}Step 6: Creating database schema...${NC}"
psql -U "$DB_USER" -d "$DB_NAME" -f schema.sql > /dev/null 2>&1
echo -e "${GREEN}✓ Schema created${NC}"

# Verify schema
echo -e "${YELLOW}Step 7: Verifying schema...${NC}"
TABLE_COUNT=$(psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' ')
echo -e "${GREEN}✓ Found $TABLE_COUNT tables${NC}"

echo ""
echo -e "${GREEN}=========================================="
echo "Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Review and update .env file with your PostgreSQL credentials"
echo "2. Run: python ingest.py"
echo "3. Check TESTING.md for detailed testing instructions"
echo ""


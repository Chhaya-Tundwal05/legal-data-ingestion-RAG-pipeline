# Deployment Guide - Run Independently

This guide shows you how to run the pipeline independently without installing dependencies on your local machine.

## Option 1: Docker (Recommended - Self-Contained)

### Prerequisites
- Docker Desktop installed (https://www.docker.com/products/docker-desktop/)
- OR Docker Engine on Linux

### Quick Start with Docker Compose

```bash
# 1. Navigate to project directory
cd "/Users/icg/Downloads/OurFirm Assesment"

# 2. Build and run everything (PostgreSQL + Ingestion)
docker-compose up

# This will:
# - Start PostgreSQL container
# - Create database and schema
# - Run the ingestion
# - Show logs and results
```

### Using Docker Manually

```bash
# 1. Build the Docker image
docker build -t legal-dockets-ingestion .

# 2. Start PostgreSQL (if not already running)
docker run -d \
  --name legal_dockets_db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=legal_dockets \
  -p 5432:5432 \
  postgres:15-alpine

# 3. Wait for PostgreSQL to be ready
sleep 5

# 4. Create schema
docker exec -i legal_dockets_db psql -U postgres -d legal_dockets < schema.sql

# 5. Run ingestion
docker run --rm \
  --link legal_dockets_db:postgres \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_NAME=legal_dockets \
  -e DB_USER=postgres \
  -e DB_PASSWORD=postgres \
  -v $(pwd)/quarantine:/app/quarantine \
  -v $(pwd)/ingestion.log:/app/ingestion.log \
  legal-dockets-ingestion
```

### View Results

```bash
# Connect to database
docker exec -it legal_dockets_db psql -U postgres -d legal_dockets

# View tables
\dt

# Check cases
SELECT COUNT(*) FROM cases;

# Exit
\q
```

### Clean Up

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (deletes data)
docker-compose down -v
```

---

## Option 2: Remote Server / Cloud

### Copy Files to Remote Server

```bash
# Create a deployment package
tar -czf legal-dockets-pipeline.tar.gz \
  ingest.py \
  schema.sql \
  raw_dockets.json \
  requirements.txt \
  .env.example \
  Dockerfile \
  docker-compose.yml

# Copy to remote server
scp legal-dockets-pipeline.tar.gz user@remote-server:/path/to/destination/

# On remote server, extract and run
ssh user@remote-server
cd /path/to/destination
tar -xzf legal-dockets-pipeline.tar.gz
docker-compose up
```

### Using Cloud Services

#### AWS EC2 / Lightsail
1. Launch an instance with Docker pre-installed
2. Copy files via SCP
3. Run `docker-compose up`

#### Google Cloud Run
1. Build and push Docker image to GCR
2. Deploy with Cloud SQL for PostgreSQL
3. Run as a job

#### Azure Container Instances
1. Build and push Docker image to ACR
2. Create container instance with Azure Database for PostgreSQL

---

## Option 3: Virtual Environment (Portable)

If you want to run on another machine with Python but without Docker:

### Create Portable Package

```bash
# 1. Create deployment directory
mkdir -p deployment
cd deployment

# 2. Copy necessary files
cp ../ingest.py .
cp ../schema.sql .
cp ../raw_dockets.json .
cp ../requirements.txt .

# 3. Create setup script
cat > setup.sh << 'EOF'
#!/bin/bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=legal_dockets
DB_USER=postgres
DB_PASSWORD=postgres
JSON_FILE=raw_dockets.json
QUARANTINE_DIR=quarantine
EOL

echo "Setup complete! Activate with: source venv/bin/activate"
EOF

chmod +x setup.sh

# 4. Create run script
cat > run.sh << 'EOF'
#!/bin/bash
source venv/bin/activate
python ingest.py
EOF

chmod +x run.sh

# 5. Create README
cat > README.txt << 'EOF'
SETUP:
1. Run: ./setup.sh
2. Ensure PostgreSQL is installed and running
3. Create database: createdb legal_dockets
4. Create schema: psql -d legal_dockets -f schema.sql
5. Run: ./run.sh
EOF

# 6. Package everything
cd ..
tar -czf legal-dockets-portable.tar.gz deployment/
```

### On Target Machine

```bash
# Extract
tar -xzf legal-dockets-portable.tar.gz
cd deployment

# Run setup
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Setup database (if not done)
createdb legal_dockets
psql -d legal_dockets -f schema.sql

# Run ingestion
./run.sh
```

---

## Option 4: Package as Docker Image

Build and share the Docker image:

```bash
# Build image
docker build -t legal-dockets-ingestion:latest .

# Save image to file
docker save legal-dockets-ingestion:latest | gzip > legal-dockets-image.tar.gz

# On another machine, load image
docker load < legal-dockets-image.tar.gz

# Run with your PostgreSQL connection
docker run --rm \
  -e DB_HOST=your-postgres-host \
  -e DB_USER=your-user \
  -e DB_PASSWORD=your-password \
  -e DB_NAME=legal_dockets \
  legal-dockets-ingestion:latest
```

---

## Recommended: Docker Compose (Easiest)

The **docker-compose.yml** file is the easiest way to run everything independently:

```bash
# Single command to run everything
docker-compose up

# View logs
docker-compose logs -f

# Stop everything
docker-compose down
```

This approach:
- ✅ No local dependencies needed (except Docker)
- ✅ Self-contained PostgreSQL
- ✅ Automatic schema setup
- ✅ Easy to share and deploy
- ✅ Works on any machine with Docker

---

## Troubleshooting

### Docker not installed?
- macOS: Download Docker Desktop from https://www.docker.com/products/docker-desktop/
- Linux: `sudo apt-get install docker.io docker-compose`
- Windows: Download Docker Desktop

### Port 5432 already in use?
Edit `docker-compose.yml` and change:
```yaml
ports:
  - "5433:5432"  # Use different port
```

### Need to connect to existing PostgreSQL?
Edit `docker-compose.yml` and remove the `postgres` service, then update environment variables to point to your existing database.


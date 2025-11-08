# Run Independently - Quick Guide

## 🐳 Option 1: Docker Compose (Easiest - Recommended)

**Prerequisites:** Docker Desktop installed

```bash
# Single command to run everything
docker-compose up

# That's it! This will:
# - Start PostgreSQL
# - Create database and schema
# - Run ingestion on all 502 records
# - Show results
```

**To stop:**
```bash
docker-compose down
```

**To view results:**
```bash
# Connect to database
docker exec -it legal_dockets_db psql -U postgres -d legal_dockets

# Check counts
SELECT COUNT(*) FROM cases;
SELECT COUNT(*) FROM courts;
SELECT COUNT(*) FROM parties;

# Exit
\q
```

---

## 📦 Option 2: Package for Remote Server

### Create Package

```bash
# Package everything needed
tar -czf legal-dockets-pipeline.tar.gz \
  ingest.py \
  schema.sql \
  raw_dockets.json \
  requirements.txt \
  Dockerfile \
  docker-compose.yml \
  .dockerignore
```

### On Remote Server

```bash
# Extract
tar -xzf legal-dockets-pipeline.tar.gz

# Run
docker-compose up
```

---

## 🚀 Option 3: Cloud Deployment

### AWS / GCP / Azure

1. Copy files to cloud instance
2. Install Docker: `sudo apt-get install docker.io docker-compose`
3. Run: `docker-compose up`

### Or use managed services:
- **AWS**: ECS Fargate + RDS
- **GCP**: Cloud Run + Cloud SQL
- **Azure**: Container Instances + Azure Database

---

## 📋 What You Get

After running, you'll have:
- ✅ All 502 records processed
- ✅ Database with normalized data
- ✅ Name variations tracked
- ✅ Failed records in `quarantine/` folder
- ✅ Error logs in `ingestion.log`
- ✅ JSON summary with counts

---

## 🔍 Verify Results

```bash
# Check ingestion runs
docker exec -it legal_dockets_db psql -U postgres -d legal_dockets -c \
  "SELECT run_id, total_read, total_inserted, total_updated, total_failed FROM ingest_runs;"

# Check name variations
docker exec -it legal_dockets_db psql -U postgres -d legal_dockets -c \
  "SELECT c.name, COUNT(cnv.raw_name) as variations FROM courts c JOIN court_name_variations cnv ON c.id = cnv.court_id GROUP BY c.id, c.name LIMIT 5;"
```

---

## 💡 Tips

- **No Docker?** Install Docker Desktop from https://www.docker.com/products/docker-desktop/
- **Port conflict?** Edit `docker-compose.yml` port mapping
- **Different credentials?** Edit environment variables in `docker-compose.yml`
- **Keep data?** Data persists in Docker volume (use `docker-compose down -v` to remove)

---

## 📁 Files Created

- `Dockerfile` - Container definition
- `docker-compose.yml` - Complete setup (PostgreSQL + Ingestion)
- `.dockerignore` - Excludes unnecessary files
- `DEPLOYMENT.md` - Detailed deployment guide


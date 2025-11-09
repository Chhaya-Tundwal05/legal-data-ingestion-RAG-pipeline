.PHONY: up down logs psql sh ingest fix-collation reset-db

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f db

psql:
	docker compose exec db psql -U postgres -d dockets

sh:
	docker compose exec app bash

ingest:
	# usage: make ingest FILE=data/raw_dockets.json
	docker compose exec app python ingest.py --file $(FILE)

fix-collation:
	# Fix collation version mismatch for existing database
	docker compose exec db psql -U postgres -d dockets -c "ALTER DATABASE dockets REFRESH COLLATION VERSION;"

reset-db:
	# WARNING: This will delete all data! Resets the database volume and re-applies schema.sql
	docker compose down -v
	docker compose up -d


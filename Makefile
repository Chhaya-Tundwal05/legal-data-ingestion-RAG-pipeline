.PHONY: up down logs psql sh ingest

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


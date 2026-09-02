SHELL := /bin/sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api pytest
	docker compose run --rm frontend npm test

backup:
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-stock} $${POSTGRES_DB:-stock_monitor} | gzip > stock-monitor-$$(date +%F-%H%M).sql.gz

restore:
	@test -n "$(FILE)" || (printf '请使用 make restore FILE=backup.sql.gz\n' && exit 1)
	gunzip -c "$(FILE)" | docker compose exec -T postgres psql -U $${POSTGRES_USER:-stock} $${POSTGRES_DB:-stock_monitor}

# Native macOS development. Docker targets above remain the production path.
native-bootstrap:
	brew bundle --file Brewfile
	./scripts/dev-macos bootstrap

native-services:
	./scripts/dev-macos services-start

native-services-stop:
	./scripts/dev-macos services-stop

native-doctor:
	./scripts/dev-macos doctor

native-migrate:
	./scripts/dev-macos migrate

native-api:
	./scripts/dev-macos api

native-worker:
	./scripts/dev-macos worker

native-beat:
	./scripts/dev-macos beat

native-finnhub:
	./scripts/dev-macos finnhub

native-frontend:
	./scripts/dev-macos frontend

native-status:
	./scripts/dev-macos status

native-test:
	./scripts/dev-macos test-backend
	./scripts/dev-macos test-frontend

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

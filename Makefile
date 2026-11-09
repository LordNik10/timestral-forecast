.PHONY: setup dev backend frontend test test-fast lint build samples

# Installa le dipendenze di backend (uv, da lockfile) e frontend (npm).
setup:
	cd backend && uv sync
	cd frontend && npm install

# Avvia backend (localhost:8000) e frontend (localhost:3000) insieme; Ctrl+C li ferma entrambi.
dev:
	cd frontend && npm run dev:all

backend:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

# Tutti i test: backend (inclusi gli smoke test slow con Timestral-5M) e controlli del frontend.
test:
	cd backend && uv run pytest
	cd backend && uv run ruff check app tests
	cd frontend && npm run typecheck && npm run lint && npm run build

# Solo i test veloci del backend (nessun modello caricato).
test-fast:
	cd backend && uv run pytest -m "not slow"

lint:
	cd backend && uv run ruff check app tests
	cd frontend && npm run typecheck && npm run lint

build:
	cd frontend && npm run build

# Rigenera i dataset sintetici di esempio (seed fisso).
samples:
	cd backend && uv run python ../samples/genera_campioni.py

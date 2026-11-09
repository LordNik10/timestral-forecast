.PHONY: setup dev backend frontend test test-fast lint build samples

# Installa le dipendenze: Python con uv (da lockfile), JavaScript con npm workspaces (da lockfile alla radice).
setup:
	cd backend && uv sync
	npm install

# Avvia backend (localhost:8000) e frontend (localhost:3000) insieme con Turborepo; Ctrl+C li ferma entrambi.
dev:
	npx turbo run dev

backend:
	npx turbo run dev --filter=backend

frontend:
	npx turbo run dev --filter=frontend

# Tutti i controlli, con cache di Turborepo: pytest (inclusi gli smoke test slow con Timestral-5M), ruff,
# tsc, eslint e next build.
test:
	npx turbo run test lint typecheck build

# Solo i test veloci del backend (nessun modello caricato).
test-fast:
	npx turbo run test:fast

lint:
	npx turbo run lint typecheck

build:
	npx turbo run build

# Rigenera i dataset sintetici di esempio (seed fisso).
samples:
	cd backend && uv run python ../samples/genera_campioni.py

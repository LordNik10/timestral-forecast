# Scorciatoie per chi ha make: ogni target delega allo script npm omonimo alla radice (vedi package.json).
.PHONY: setup dev test test-fast lint build samples

setup:
	npm run setup

dev:
	npm run dev

test:
	npm run test

test-fast:
	npm run test:fast

lint:
	npm run lint

build:
	npm run build

samples:
	npm run samples

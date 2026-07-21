.PHONY: install install-dev run test lint check release-check docker-build

install:
	python -m pip install -r requirements.lock

install-dev:
	python -m pip install -r requirements-dev.lock

run:
	bash run.sh

test:
	python -m pytest -q

lint:
	python -m ruff check app scripts tests

check:
	python -m compileall -q app scripts
	python -m ruff check app scripts tests
	python scripts/release_check.py
	python -m pip check
	node --check web/app.js

release-check: check test

docker-build:
	docker build --tag xiaoyi-ai:0.3.0 .

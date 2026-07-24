.PHONY: install install-dev run test lint check release-check benchmark benchmark-verify benchmark-verify-deep docker-build

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

benchmark:
	python scripts/run_rag_benchmark.py run

benchmark-verify:
	python scripts/run_rag_benchmark.py verify

benchmark-verify-deep:
	python scripts/run_rag_benchmark.py verify --deep

docker-build:
	docker build --tag xiaoyi-ai:0.3.0 .

.PHONY: install install-dev run test lint check release-check benchmark benchmark-verify benchmark-verify-deep sbom sbom-verify dependency-audit-verify docker-build

BENCHMARK_TAG ?=

install:
	python -m pip install --require-hashes -r requirements.lock

install-dev:
	python -m pip install --require-hashes -r requirements-dev.lock

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
	@test -n "$(BENCHMARK_TAG)" || (echo "BENCHMARK_TAG is required, e.g. make benchmark BENCHMARK_TAG=20260814_r1" && exit 2)
	python scripts/run_rag_benchmark.py run --output-tag "$(BENCHMARK_TAG)"

benchmark-verify:
	python scripts/run_rag_benchmark.py verify --output-tag 20260814_r1

benchmark-verify-deep:
	python scripts/run_rag_benchmark.py verify --output-tag 20260814_r1 --deep

sbom:
	python scripts/build_sbom.py build

sbom-verify:
	python scripts/build_sbom.py verify

dependency-audit-verify:
	python scripts/build_dependency_audit_admission.py verify

docker-build:
	docker build --tag xiaoyi-ai:0.4.0 .

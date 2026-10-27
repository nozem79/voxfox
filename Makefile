# Build and check helpers. VERSION defaults to the APP_VERSION in the source,
# so `make deb` always matches what the About box reports.
VERSION ?= $(shell sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' src/voxfox_ui/common.py)

.PHONY: deb rpm check lint test clean

deb:
	VERSION=$(VERSION) bash packaging/build-deb.sh

rpm:
	VERSION=$(VERSION) bash packaging/build-rpm.sh

# The same checks as CI (.github/workflows/ci.yml).
check: lint
	python3 -m compileall -q src/
	python3 -m pytest -q tests/

lint:
	ruff check src/ tests/

test:
	python3 -m pytest -q tests/

clean:
	rm -f src/voxfox_*_all.deb src/voxfox-*.noarch.rpm README-deb*.html RELEASE_NOTES.md .coverage
	rm -rf .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

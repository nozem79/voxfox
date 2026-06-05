# Build/lint helpers. VERSION defaults to the APP_VERSION in the source,
# so `make deb` always matches what the About box reports.
VERSION ?= $(shell sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' src/voxfox_gtk.py)

.PHONY: deb check lint clean

deb:
	VERSION=$(VERSION) bash packaging/build-deb.sh
	@echo "Built voxfox_$(VERSION)_all.deb"

check:
	python3 -m py_compile src/voxfox_gtk.py src/voxfox_core/*.py
	@echo "compile OK"

lint:
	pyflakes src/voxfox_core/*.py src/voxfox_gtk.py || true

clean:
	rm -f voxfox_*_all.deb README-deb*.html RELEASE_NOTES.md
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

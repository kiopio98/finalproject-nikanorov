.PHONY: install project lint test build package-install publish check
install:
	uv sync --locked
project:
	uv run project
lint:
	uv run ruff check .
test:
	uv run python -m unittest discover -s tests -v
build:
	uv build
package-install: build
	uv tool install --force .
publish: build
	uv publish
check: lint test build

set fallback := true
set shell := ["bash", "-c"]

# default recipe to display help information
@list:
  just --list

# remove files created by tooling and packaging
@clean:
  rm -rf dist
  rm -rf deps
  rm -rf build
  rm -rf **/*.egg-info
  rm -rf .eggs
  rm -rf .pytest_cache
  rm -rf **/*/__pycache__
  rm -rf **/__pycache__
  rm -rf .mypy_cache
  rm -rf **/.mypy_cache
  rm -rf .ruff_cache
  rm -rf **/.ruff_cache
  rm -rf htmlcov
  rm -f public/profile.pdf
  rm -f .coverage
  rm -f .coverage.xml
  rm -f .junit.xml

# install project & dependencies without updating the .lock file
@install:
  uv sync --locked

# run pre-commit linters on all files
@lint: install
  uv run pre-commit run --all-files

# run python tests in Docker container (test stage)
@test *ARGS:
  docker build --target test -t pdf-generator-test .
  docker run --rm pdf-generator-test uv run pytest {{ ARGS }}

# run all CI checks locally
@all: clean lint test

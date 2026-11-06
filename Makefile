PY ?= .venv/bin/python

.PHONY: install migrate run seed test schema check ci

install:
	python3.10 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

migrate:
	$(PY) manage.py migrate

run:
	$(PY) manage.py runserver

seed:
	$(PY) manage.py seed_demo

test:
	$(PY) -m pytest

schema:
	$(PY) manage.py spectacular --file schema.yml --validate --fail-on-warn

check:
	$(PY) manage.py check --fail-level WARNING
	$(PY) manage.py makemigrations --check --dry-run

ci: check schema test

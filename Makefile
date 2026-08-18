.PHONY: setup resume check test dev worker scheduler ingest seed

setup:
	./.agents/setup

resume:
	./.agents/resume

check:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/python manage.py check
	.venv/bin/python manage.py makemigrations --check --dry-run
	.venv/bin/python -m compileall -q config dashboard market operations

test:
	.venv/bin/python manage.py test

dev:
	amp orb services ensure

worker:
	.venv/bin/python manage.py run_worker

scheduler:
	.venv/bin/python manage.py run_scheduler

ingest:
	.venv/bin/python manage.py ingest_oanda

seed:
	.venv/bin/python manage.py seed_demo

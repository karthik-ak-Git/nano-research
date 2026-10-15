.PHONY: install test lookup refresh batch export stats cost-report validate seed api docker-build docker-up clean

install:
	uv pip install -e .

test:
	pytest tests/ -v

lookup:
	company-agent lookup 923609016

refresh:
	company-agent refresh 923609016

batch:
	company-agent batch --input data/sample_companies.txt --output reports/batch_results.json

export:
	company-agent export --output profiles/exported_profiles.json

stats:
	company-agent stats

cost-report:
	company-agent cost-report

validate:
	company-agent validate --input profiles/seeded_profiles.json

seed:
	python scripts/seed_profiles.py --target 1000

api:
	uvicorn company_agent.api:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker build -t norwegian-company-agent:latest .

docker-up:
	docker-compose up agent-api

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

.PHONY: test test-unit test-integration install-dev

install-dev:
	pip install -r requirements-dev.txt

test: test-unit

test-unit:
	pytest tests/unit \
		--flake8 pg_data_yaml tests \
		--cov=pg_data_yaml --cov=tests \
		-p no:logging

test-integration:
	pytest tests/integration -v

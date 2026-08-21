.PHONY: venv install data profile build serve test lint typecheck demo clean

PYTHON ?= python
VENV := .venv
BIN := $(VENV)/Scripts

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	$(BIN)/pip install -e .

data:
	@echo "Raw CSVs expected in data/raw/ (14 tables). See docs/data_dictionary.md."
	@ls data/raw | wc -l

profile:
	$(PYTHON) -m agentiq.data.profile --raw data/raw --out docs/data_dictionary.md

build:
	$(PYTHON) -m agentiq.data.build_artifacts --raw data/raw --out data/artifacts

serve:
	$(PYTHON) -m uvicorn agentiq.api.main:app --reload --port 8000

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m mypy src

demo:
	@echo "Run 'make serve' then open ui/ against http://localhost:8000"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache

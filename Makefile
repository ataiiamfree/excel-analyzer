.PHONY: install run web-install web-dev web-build dev test clean lint

HOST ?= 127.0.0.1
PORT ?= 8000

install:
	pip install -r requirements.txt

run:
	uvicorn app.api.server:app --host $(HOST) --port $(PORT) --reload

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

dev:
	@echo "Run backend and frontend in two terminals:"
	@echo "  make run"
	@echo "  make web-dev"

test:
	python -m pytest tests/ -v

clean:
	rm -rf workspace/*/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

lint:
	python -m py_compile app/**/*.py

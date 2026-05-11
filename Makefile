.PHONY: install run test clean lint

install:
	pip install -r requirements.txt

run:
	uvicorn app.server:app --reload --host 0.0.0.0 --port 8000

test:
	python -m pytest tests/ -v

clean:
	rm -rf workspace/*/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

lint:
	python -m py_compile app/**/*.py

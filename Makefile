.PHONY: install run test clean lint

HOST ?= 127.0.0.1
PORT ?= 8000

install:
	pip install -r requirements.txt

run:
	chainlit run app/main.py --host $(HOST) --port $(PORT)

test:
	python -m pytest tests/ -v

clean:
	rm -rf workspace/*/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

lint:
	python -m py_compile app/**/*.py

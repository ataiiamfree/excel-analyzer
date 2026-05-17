.PHONY: install run test clean lint

install:
	pip install -r requirements.txt

run:
	@echo "app/main.py belongs to Phase 8 and is not implemented yet. Use 'make test' for current validation."
	@exit 1

test:
	python -m pytest tests/ -v

clean:
	rm -rf workspace/*/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

lint:
	python -m py_compile app/**/*.py

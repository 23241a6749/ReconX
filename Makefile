.PHONY: demo generate phase2 phase3 phase4 phase5 release test run preview clean

demo: generate
	PYTHONPATH=src python -m reconx.cli reconcile data/demo/batch.json --output artifacts/demo-result.json

generate:
	PYTHONPATH=src python -m reconx.cli generate --output data/demo/batch.json

phase2:
	PYTHONPATH=src python -m reconx.cli generate-development --output-dir data/development
	PYTHONPATH=src python -m reconx.cli evaluate-development data/development --output reports/phase2-evaluation.json

phase3:
	PYTHONPATH=src python -m reconx.cli evaluate-safety --output reports/phase3-safety-report.json

phase4:
	PYTHONPATH=src python -m reconx.cli generate-heldout --output-dir data/heldout
	PYTHONPATH=src python -m reconx.cli evaluate-heldout data/heldout --output reports/phase4-heldout-evaluation.json

phase5:
	PYTHONPATH=src python -m reconx.cli evaluate-integration --output reports/phase5-integration-report.json

release: test phase2 phase3 phase4 phase5
	python scripts/verify_release.py

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

run:
	uvicorn reconx.api:app --app-dir src --reload --host 0.0.0.0 --port 8000

preview:
	PYTHONPATH=src python -m reconx.preview

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +

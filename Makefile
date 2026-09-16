# Sandstorm iOS Driver — common tasks
SIMULATOR ?= $(shell xcrun simctl list devices available --json | python3 -c "import json,sys;d=json.load(sys.stdin)['devices'];print(next(x['udid'] for r in d for x in d[r] if x['name'].startswith('iPhone')))")
PROJECT   := ios-agent/SandstormAgent.xcodeproj
SCHEME    := SandstormAgent
DERIVED   := build/derived
PYTHONPATH_LOCAL := ios-sdk:ios-controller:ios-inspector

.PHONY: help install project build-sim test smoke lint clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t-/'

install: ## Install the Python packages in editable mode
	python3 -m pip install -e '.[dev]'

project: ## Regenerate the Xcode project
	python3 tools/generate_xcodeproj.py

build-sim: ## Build the agent for the simulator (once)
	xcodebuild build-for-testing \
	  -project $(PROJECT) -scheme $(SCHEME) \
	  -destination 'platform=iOS Simulator,id=$(SIMULATOR)' \
	  -derivedDataPath $(DERIVED) -quiet

test: ## Run host-side unit tests (no device needed)
	python3 -m pytest -q

smoke: ## Full phase 1-3 run against a simulator
	PYTHONPATH=$(PYTHONPATH_LOCAL) python3 examples/smoke_simulator.py $(SIMULATOR)

lint: ## Ruff + mypy
	python3 -m ruff check ios-sdk ios-controller ios-inspector tools examples
	python3 -m mypy ios-sdk/sandstorm_ios

clean:
	rm -rf build .pytest_cache

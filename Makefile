SHELL := /bin/bash
VENV  := .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

# ── Default target ────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  Strides AI"
	@echo ""
	@echo "  make install   Install Python and Node dependencies"
	@echo "  make dev       Run API + frontend together  (Ctrl+C stops both)"
	@echo "  make api       Run the FastAPI server only  (localhost:8000)"
	@echo "  make web       Run the Vite frontend only   (localhost:5173)"
	@echo "  make cli       Launch the terminal coaching app"
	@echo "  make profile   Edit your athlete profile in \$$EDITOR"
	@echo ""

# ── Install ───────────────────────────────────────────────────────────────────
.PHONY: install
install: $(VENV)/bin/activate web/node_modules

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install -e ".[dev]"
	$(VENV)/bin/pre-commit install

# Re-run pip if pyproject.toml is newer than the venv marker
$(VENV)/bin/strides-ai: pyproject.toml $(VENV)/bin/activate
	$(PIP) install -e .

web/node_modules: web/package.json
	cd web && npm install --silent

# ── Run ───────────────────────────────────────────────────────────────────────
.PHONY: dev
dev: _check_env $(VENV)/bin/strides-ai web/node_modules
	@echo "Starting API on :8000 and frontend on :5173 — press Ctrl+C to stop both"
	@trap 'kill 0' INT; \
	 $(VENV)/bin/strides-ai-web & \
	 (cd web && npm run dev) & \
	 wait

.PHONY: api
api: _check_env $(VENV)/bin/strides-ai
	$(VENV)/bin/strides-ai-web

.PHONY: web
web: web/node_modules
	cd web && npm run dev

.PHONY: cli
cli: _check_env $(VENV)/bin/strides-ai
	$(VENV)/bin/strides-ai

.PHONY: profile
profile: $(VENV)/bin/strides-ai
	$(VENV)/bin/strides-ai --setup-profile

# ── Test ──────────────────────────────────────────────────────────────────────
.PHONY: test
test: $(VENV)/bin/activate
	$(PY) -m pytest tests/ -v

# ── Helpers ───────────────────────────────────────────────────────────────────
.PHONY: _check_env
_check_env:
	@if [ ! -f .env ]; then \
	  echo ""; \
	  echo "  No .env file found."; \
	  echo "  Run: cp .env.example .env  then fill in your credentials."; \
	  echo ""; \
	  exit 1; \
	fi

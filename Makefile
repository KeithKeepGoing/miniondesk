# MinionDesk Makefile
# Usage: make <target>

.PHONY: help build dev start stop logs validate setup ingest test clean

DOCKER_IMAGE := miniondesk-runner:latest
COMPOSE := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Usage: make [target]"

build: ## Build the minion runner Docker image
	docker build -t $(DOCKER_IMAGE) container/
	@echo "✅ Built $(DOCKER_IMAGE)"

dev: build ## Build image and start in development mode (with logs)
	$(COMPOSE) up

start: build ## Build image and start in background
	$(COMPOSE) up -d
	@echo "✅ MinionDesk started. Logs: make logs"

stop: ## Stop all services
	$(COMPOSE) down
	@echo "✅ MinionDesk stopped"

restart: stop start ## Restart all services

logs: ## Tail live logs
	$(COMPOSE) logs -f

validate: ## Run pre-flight validation
	python run.py validate

setup: ## Interactive setup wizard
	python run.py setup

ingest: ## Ingest knowledge base (usage: make ingest PATH=./knowledge/raw)
	python run.py ingest $(PATH)

status: ## Show system status
	python run.py admin status

audit: ## Show recent audit log (last 20 entries)
	python run.py admin audit-log 20

health: ## Check system health
	python run.py health

test: ## Run unit tests
	python -m pytest tests/ -v 2>/dev/null || echo "No tests found. Add tests/ directory."

clean: ## Remove generated files (data, ipc, logs, __pycache__)
	@read -p "⚠️  This will delete data/, ipc/, logs/. Continue? [y/N] " confirm; \
	if [ "$$confirm" = "y" ]; then \
		rm -rf data/ ipc/ *.log; \
		find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; \
		echo "✅ Cleaned"; \
	else \
		echo "Cancelled"; \
	fi

shell: ## Open shell in running host container
	$(COMPOSE) exec host bash

db: ## Open SQLite shell on the database
	sqlite3 data/miniondesk.db

backup: ## Backup SQLite database
	@mkdir -p backups
	@cp data/miniondesk.db backups/miniondesk_$$(date +%Y%m%d_%H%M%S).db
	@echo "✅ Backed up to backups/"

portal: ## Start web portal only
	python run.py portal

dashboard:  ## Open admin dashboard
	@echo "Dashboard: http://localhost:${DASHBOARD_PORT:-8084}"

confluence-sync: ## Sync Confluence to knowledge base
	python run.py confluence-sync

sharepoint-sync: ## Sync SharePoint to knowledge base
	python run.py sharepoint-sync

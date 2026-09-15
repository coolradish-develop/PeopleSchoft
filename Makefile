.PHONY: start seed reset demo sync status test mock-okta journey
PORT ?= 8080

start:        ## Start web UI + API (seeds on first run)
	./start.sh $(PORT)
seed:         ## Create schema + demo data if empty
	python3 -m peopleschoft seed
reset:        ## Drop everything and re-seed
	python3 -m peopleschoft reset --yes
demo:         ## Run the joiner/mover/leaver/rehire journey from the CLI
	python3 -m peopleschoft demo
sync:         ## Flush the Okta outbox once
	python3 -m peopleschoft okta-sync
export-sql:   ## Print HR master SQL for the Okta Generic Databases connector (DIALECT=postgres|mysql|mssql)
	python3 -m peopleschoft export-sql --dialect $(or $(DIALECT),postgres)
status:       ## Counts + Okta configuration
	python3 -m peopleschoft status
test:         ## Run the unit tests
	python3 -m unittest -v
mock-okta:    ## Start a fake Okta org on :9090 (users / webhook / identity-source modes work against it)
	python3 scripts/mock_okta.py --port 9090
mock-oag:     ## Start a fake Okta Access Gateway on :8443 in front of the app (header-based SSO demo)
	python3 scripts/mock_oag.py --port 8443 --upstream http://localhost:$(PORT)
journey:      ## Drive the lifecycle journey with curl against a running server
	./scripts/demo_journey.sh http://localhost:$(PORT)
docker-files: ## Generate Dockerfile, docker-compose.yml and .dockerignore
	python3 scripts/generate_docker.py --port $(PORT)

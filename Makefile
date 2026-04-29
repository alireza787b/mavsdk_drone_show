SHELL := /bin/bash

GCS_API ?= http://localhost:5030
SITL_COUNT ?= 4
START_FLAGS ?=
PYTEST_ARGS ?=
NPM_TEST_ARGS ?= -- --watchAll=false
ARGS ?=

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show common MDS operator, maintainer, and CI commands.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: status
status: ## Print local GCS launcher/runtime status.
	bash app/linux_dashboard_start.sh --status

.PHONY: gcs-sitl
gcs-sitl: ## Start the GCS in SITL mode. Extra flags: make gcs-sitl START_FLAGS="--prod --skip-deps".
	bash app/linux_dashboard_start.sh --sitl $(START_FLAGS)

.PHONY: gcs-real
gcs-real: ## Start the GCS in REAL/hardware mode. Extra flags: make gcs-real START_FLAGS="--prod --skip-deps".
	bash app/linux_dashboard_start.sh --real $(START_FLAGS)

.PHONY: gcs-prod-sitl
gcs-prod-sitl: ## Build/serve the dashboard and start the GCS in production SITL mode.
	bash app/linux_dashboard_start.sh --prod --sitl $(START_FLAGS)

.PHONY: gcs-prod-real
gcs-prod-real: ## Build/serve the dashboard and start the GCS in production REAL/hardware mode.
	bash app/linux_dashboard_start.sh --prod --real $(START_FLAGS)

.PHONY: gcs-stop
gcs-stop: ## Stop the local GCS launcher session.
	bash app/linux_dashboard_start.sh --stop

.PHONY: gcs-update
gcs-update: ## Fast-forward the local GCS checkout through the guarded update script.
	bash tools/gcs_fast_forward_update.sh $(ARGS)

.PHONY: install-gcs
install-gcs: ## Install or repair a GCS host through the canonical bootstrap script.
	sudo bash tools/install_gcs.sh $(ARGS)

.PHONY: install-companion
install-companion: ## Install a fresh companion node through the public installer wrapper.
	sudo bash tools/install_companion.sh $(ARGS)

.PHONY: node-init
node-init: ## Run companion-node bootstrap from an already cloned repo.
	sudo bash tools/mds_node_init.sh $(ARGS)

.PHONY: node-resume
node-resume: ## Resume or repair an interrupted companion-node bootstrap.
	sudo bash tools/mds_node_init.sh --resume $(ARGS)

.PHONY: git-access-check
git-access-check: ## Validate non-interactive git access for the configured repo/branch.
	bash tools/mds_git_access_check.sh $(ARGS)

.PHONY: auth-status
auth-status: ## Print dashboard/API auth posture, users, and token metadata.
	sudo python3 tools/mds_auth_admin.py status

.PHONY: auth-add-user
auth-add-user: ## Create/reset a dashboard user. Example: make auth-add-user ARGS="admin --role admin".
	sudo python3 tools/mds_auth_admin.py add-user $(ARGS)

.PHONY: auth-enable-dashboard
auth-enable-dashboard: ## Enable dashboard login in /etc/mds/gcs.env; restart GCS to apply.
	sudo python3 tools/mds_auth_admin.py enable-dashboard

.PHONY: auth-disable-dashboard
auth-disable-dashboard: ## Disable dashboard login in /etc/mds/gcs.env; restart GCS to apply.
	sudo python3 tools/mds_auth_admin.py disable-dashboard

.PHONY: auth-create-token
auth-create-token: ## Create an API/debug token. Example: make auth-create-token ARGS="--name field-debug --scope readonly --ttl-hours 4".
	sudo python3 tools/mds_auth_admin.py create-token $(ARGS)

.PHONY: auth-revoke-token
auth-revoke-token: ## Revoke an API token by id. Example: make auth-revoke-token ARGS="tok_abcd".
	sudo python3 tools/mds_auth_admin.py revoke-token $(ARGS)

.PHONY: fleet-git-status
fleet-git-status: ## Query GCS aggregated fleet git/auth/sidecar status.
	curl -sS "$(GCS_API)/api/v1/git/status"

.PHONY: fleet-sync
fleet-sync: ## Trigger the same GCS-managed drone sync operation used by the dashboard.
	curl -sS -X POST "$(GCS_API)/api/v1/git/sync-operations" -H 'Content-Type: application/json' -d '{}'

.PHONY: sitl-status
sitl-status: ## List local SITL instances through the GCS API.
	curl -sS "$(GCS_API)/api/v1/system/sitl/instances"

.PHONY: sitl-reconcile
sitl-reconcile: ## Reconcile local SITL to SITL_COUNT containers.
	curl -sS -X POST "$(GCS_API)/api/v1/system/sitl/reconcile" -H 'Content-Type: application/json' -d '{"target_count":$(SITL_COUNT)}'

.PHONY: sitl-stop
sitl-stop: ## Remove all local SITL containers through the supported GCS SITL API.
	python3 tools/sitl_stop_all.py --gcs-api "$(GCS_API)"

.PHONY: test-python
test-python: ## Run Python tests. Extra args: make test-python PYTEST_ARGS="tests/test_file.py -q".
	python3 -m pytest $(PYTEST_ARGS)

.PHONY: test-frontend
test-frontend: ## Run React tests. Extra args: make test-frontend NPM_TEST_ARGS="-- --watchAll=false --runInBand".
	cd app/dashboard/drone-dashboard && npm test $(NPM_TEST_ARGS)

.PHONY: build-frontend
build-frontend: ## Build the React dashboard production bundle.
	cd app/dashboard/drone-dashboard && npm run build

.PHONY: lint-shell
lint-shell: ## Syntax-check the primary shell entrypoints.
	bash -n app/linux_dashboard_start.sh
	bash -n tools/install_gcs.sh
	bash -n tools/install_companion.sh
	bash -n tools/install_mds_node.sh
	bash -n tools/mds_gcs_init.sh
	bash -n tools/mds_node_init.sh

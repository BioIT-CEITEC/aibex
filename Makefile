# Aibex View – common tasks. Run from the repo root.
NS ?= bystry-ns
BUNDLE ?=

.PHONY: help dev dev-backend dev-frontend test accept accept-phase accept-live e2e eval-llm k8s-secret deploy restart status logs upload-data url

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

dev: ## backend (8000) + frontend (5173) with reload
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## backend only
	cd backend && uv run uvicorn aibex.main:app --reload --port 8000

dev-frontend: ## frontend only (needs frontend/package.json)
	@if [ -f frontend/package.json ]; then cd frontend && npm run dev; else echo "frontend not created yet"; fi

test: ## unit tests + lint only (no acceptance tests; + frontend checks when present)
	cd backend && uv run ruff check . && uv run pytest -q --ignore=tests/acceptance
	@if [ -f frontend/package.json ]; then cd frontend && npm run -s typecheck --if-present && npm run -s lint --if-present; fi

accept: ## all acceptance tests (no live LLM)
	cd backend && uv run pytest -q tests/acceptance -m "not live" $(ARGS)

accept-phase: ## acceptance tests of one phase: make accept-phase P=2
	@test -n "$(P)" || (echo "usage: make accept-phase P=<1-4>" && exit 1)
	cd backend && uv run pytest -q tests/acceptance -m "phase$(P) and not live" $(ARGS)

accept-live: ## live tests against the real e-INFRA model (reads .env; be nice to the shared service)
	cd backend && uv run pytest -q tests/acceptance -m live $(ARGS)

e2e: ## Playwright e2e (FakeProvider + toy bundle); make e2e ARGS=e2e/chat.spec.ts
	@if [ -f frontend/playwright.config.ts ]; then cd frontend && npx playwright test $(ARGS); \
	else echo "e2e not set up: frontend/playwright.config.ts missing"; exit 1; fi

eval-llm: ## compare LLMs on tool calling (reads .env)
	uv run scripts/llm_eval.py $(ARGS)

k8s-secret: ## create/update the LLM secret in the cluster from .env (key never printed)
	@grep -E '^LLM_(BASE_URL|API_KEY|MODEL_FAST|MODEL_CODE)=' .env > .env.llm
	kubectl -n $(NS) create secret generic aibex-llm --from-env-file=.env.llm --dry-run=client -o yaml | kubectl -n $(NS) apply -f -
	@rm -f .env.llm

deploy: ## apply all manifests (pvc, deployment, service, ingress)
	kubectl apply -k deploy/k8s

restart: ## re-clone the branch and rebuild (after git push)
	kubectl -n $(NS) rollout restart deploy/aibex
	kubectl -n $(NS) rollout status deploy/aibex --timeout=10m

status: ## pods, ingress, pvc
	kubectl -n $(NS) get pods,svc,ingress,pvc -l app=aibex

logs: ## follow app logs
	kubectl -n $(NS) logs deploy/aibex -c aibex -f --tail=100

upload-data: ## copy a local bundle folder to the cluster volume: make upload-data BUNDLE=path/to/bundle
	@test -n "$(BUNDLE)" || (echo "usage: make upload-data BUNDLE=path/to/<bundle-id>" && exit 1)
	kubectl -n $(NS) cp "$(BUNDLE)" "$$(kubectl -n $(NS) get pod -l app=aibex -o jsonpath='{.items[0].metadata.name}'):/data/$$(basename "$(BUNDLE)")" -c aibex

url: ## print the public URL
	@echo "https://$$(kubectl -n $(NS) get ingress aibex -o jsonpath='{.spec.rules[0].host}')"

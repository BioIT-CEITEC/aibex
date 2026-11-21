# Aibex View – common tasks. Run from the repo root.
NS ?= bystry-ns
BUNDLE ?=

.PHONY: help dev dev-backend dev-frontend test eval-llm k8s-secret deploy restart status logs upload-data url

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

dev: ## backend (8000) + frontend (5173) with reload
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## backend only
	cd backend && uv run uvicorn aibex.main:app --reload --port 8000

dev-frontend: ## frontend only (needs frontend/package.json)
	@if [ -f frontend/package.json ]; then cd frontend && npm run dev; else echo "frontend not created yet"; fi

test: ## backend tests (+ frontend checks when present)
	cd backend && uv run pytest -q
	@if [ -f frontend/package.json ]; then cd frontend && npm run -s typecheck --if-present && npm run -s lint --if-present; fi

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

# Deployment – kuba-cluster (CERIT-SC, e-INFRA CZ)

Namespace **`bystry-ns`** (a personal Rancher project). kubectl runs from the developer's Mac
with a kubeconfig downloaded from Rancher (rancher.cloud.e-infra.cz → kuba-cluster → Download KubeConfig).
`kubectl get ns` is forbidden on Rancher – always pass `-n bystry-ns` (the Makefile does).

## How it runs (option C – no image registry)
- `deploy/k8s/deployment.yaml`: init container 1 clones `github.com/BioIT-CEITEC/aibex` (branch `main`),
  init container 2 builds the frontend with Node 22, the main container (python:3.12-slim) installs the backend
  with uv and starts uvicorn on port 8000. First start takes a few minutes.
- Updating = push to GitHub, then `make restart`.
- To deploy another branch for testing, change `GIT_BRANCH` in the deployment (or `kubectl set env`).
- Later: replace with a prebuilt image (GHCR via GitHub Actions, or the OmiCZ Harbor + Fleet pipeline).
- Production build (checked locally 2026-11-22, T54): `npm run build` (Node ≥ 22.12, Vite 8) writes `frontend/dist`
  (~6.7 MB, mostly Plotly 4.6 MB and the inlined widget runtime 1.4 MB). uvicorn serves it at `/`
  (`AIBEX_FRONTEND_DIST`), `/api/*` keeps priority. The app gzips responses ≥ 1 KB itself (ingress-nginx does not by
  default), so the first page load is ~2 MB on the wire; chat SSE (`text/event-stream`) is never compressed.
  No manifest change is needed. The build init container (node:22-slim, 3 Gi limit) is enough.

## First deployment
```bash
make k8s-secret      # LLM settings from .env → Secret aibex-llm (key not printed)
make deploy          # PVC, Deployment, Service, Ingress
make status          # wait until the pod is Running/Ready
make logs
make url             # https://aibex.dyn.cloud.e-infra.cz
make upload-data BUNDLE=/path/to/data/airway   # copy a bundle onto the /data volume
```

## Cluster conventions (copied from the OmiCZ services on the same cluster)
- Pods: `runAsNonRoot`, uid 1000, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, drop ALL capabilities, explicit requests/limits.
- Ingress: class `nginx`, `cert-manager.io/cluster-issuer: letsencrypt-prod`, `kubernetes.io/tls-acme: "true"`, host `<name>.dyn.cloud.e-infra.cz`.
- Public images from docker.io / ghcr.io pull without secrets.

## Troubleshooting
- Pod stuck in `Init`: `kubectl -n bystry-ns logs deploy/aibex -c clone` (or `-c build-frontend`). If pods have no internet egress, git/npm/pip fail → switch to a prebuilt image.
- PVC `Pending`: the namespace may need an explicit `storageClassName` – check `kubectl get storageclass` (?) and add it to `pvc.yaml`.
- Certificate not issued: `kubectl -n bystry-ns describe certificate` / check the host is not used elsewhere.

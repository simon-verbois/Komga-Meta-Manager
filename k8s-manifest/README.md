# Kubernetes deployment

These manifests deploy one Komga Meta Manager scheduler/watcher pod with persistent caches and secrets separated from the ConfigMap.

## Prerequisites

- A Kubernetes cluster and `kubectl`
- A working Komga Service URL reachable from the namespace
- A storage class compatible with `ReadWriteOnce`

## Configuration

1. Adjust `01-pvc.yaml`, especially `storageClassName`.
2. Adjust the Komga URL, libraries and processing options in `02-configmap.yaml`.
3. Create the untracked Secret manifest:

```bash
cp 04-secret.yaml.template 04-secret.yaml
$EDITOR 04-secret.yaml
```

`komga-api-key` is required. Remove `deepl-api-key` when translation is disabled or Google Translate is selected. Never commit `04-secret.yaml`.

## Deployment

```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-pvc.yaml
kubectl apply -f 02-configmap.yaml
kubectl apply -f 04-secret.yaml
kubectl apply -f 03-deployment.yaml

kubectl get pods -n komga-meta-manager
kubectl logs -f deployment/komga-meta-manager -n komga-meta-manager
```

The startup and readiness probes become successful only after configuration and continuous-mode initialization complete. A watcher-only deployment exits when its initial Komga connection fails; scheduler mode remains available if only watcher initialization fails.

The image runs as UID/GID 1000 with a read-only root filesystem. `/config/cache` is backed by the PVC and `/tmp` by an ephemeral volume.

# Kubernetes deployment

These manifests deploy Komga Meta Manager with its Web UI, scheduler/watcher, persistent storage, and Kubernetes Service.

## Prerequisites

- A Kubernetes cluster and `kubectl`
- A working Komga Service URL reachable from the namespace
- A storage class compatible with `ReadWriteOnce`

## Configuration

1. Adjust `01-pvc.yaml`, especially `storageClassName`. The PVC is mounted at `/config` to persist `webui.db` and the metadata cache across pod restarts.
2. Configure API keys directly in the Web UI. For a legacy YAML import only, you can optionally create secrets injected as environment variables:

```bash
cp 04-secret.yaml.template 04-secret.yaml
$EDITOR 04-secret.yaml
```

`komga-api-key` and `deepl-api-key` can also be entered directly in the Web UI.

## Deployment

```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-pvc.yaml
# Optional, for legacy migration: kubectl apply -f 04-secret.yaml
kubectl apply -f 03-deployment.yaml
kubectl apply -f 05-service.yaml

kubectl get pods -n komga-meta-manager
kubectl logs -f deployment/komga-meta-manager -n komga-meta-manager
```

Access the Web UI at port 8765 via Port-Forward or Ingress:

```bash
kubectl port-forward -n komga-meta-manager svc/komga-meta-manager 8765:8765
```

Navigate to `http://localhost:8765` to create the administrator account and configure settings.

The image runs as UID/GID 1000 with a read-only root filesystem. `/config` is backed by the PVC and `/tmp` by an ephemeral volume.

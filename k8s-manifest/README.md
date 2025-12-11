# Kubernetes Deployment

Complete manifests for deploying Komga Meta Manager to Kubernetes.

## Prerequisites

- Kubernetes cluster with admin access
- Docker registry access

## Configuration

Adjust the configurations files based on your cluster.

## Deploy

```bash
# Rename templates files

# Apply all manifests
kubectl apply -f .

# Check status
kubectl get pods -n komga-meta-manager
kubectl logs -f deployment/komga-meta-manager -n komga-meta-manager

# Kubernetes


## Manual Deployment

Create a namespace

```shell
kubectl create namespace octopus-usage-exporter
```

Create your API Key Secret

```shell
kubectl create secret generic octopus --namespace=octopus-usage-exporter --from-literal=API_KEY="<YOUR API KEY HERE>" --type=Opaque
```

Modify the Environment variables in [examples/kubernetes/deployment.yaml](examples/kubernetes/deployment.yaml)

Deploy the application and Prometheus config

```shell
kubectl apply -f examples/kubernetes
```

## Kustomize

Create a file called `kustomization.yaml`

In that file put the below:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - https://github.com/JosephRPalmer/octopus-usage-exporter
configMapGenerator:
  - name: octopus
    behavior: replace
    literals:
      - ACCOUNT_NUMBER=<change me>
      - PROM_PORT=9200
      - INTERVAL=30
      - GAS=True|False
      - ELECTRIC=True|False
      - NG_METRICS=True|False
      - TARIFF_RATES=True|False
      - TARIFF_REMAINING=True|False
```

You can then modify the configuration here, supplying the Environment variables and their values as you see fit.

This method means you are able to deploy this via means like [Flux CD](https://fluxcd.io/flux/components/source/gitrepositories/)

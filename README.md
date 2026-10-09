# MatchLab Infra

Kubernetes-манифесты и GitOps MatchLab на Flux CD и Kustomize. Код, Dockerfile, миграции и ручная сборка образов находятся в [matchlab-backend](https://github.com/HSE-Scientists-Team/matchlab-backend).

## Структура

- `clusters/homelab/` — Flux, namespace приложения и версии образов в `images.yaml`.
- `apps/secrets/` — Kubernetes Secret, зашифрованные SOPS/age; private key находится вне Git.
- `apps/platform/` — PostgreSQL с локальным PVC и Redis.
- `apps/backend/` — четыре backend-сервиса, Scalar, ConfigMap и публичный Ingress Gateway.
- `.github/workflows/validate.yml` — проверка сборки Kustomize.

## GitOps

Успешная ручная сборка в backend может создать PR с digest выбранных образов. После слияния Flux обновляет соответствующие Deployment. Секреты расшифровывает Flux; платформенные сервисы зависят от Secret, backend — от готовности платформы. Все четыре backend-сервиса применяют общий SQL-набор перед открытием API под PostgreSQL advisory-блокировкой.

Несекретная конфигурация монтируется из ConfigMap, пароли передаются через ссылки `secretKeyRef`. Scalar доступен через `/docs/` на origin Gateway. PostgreSQL закреплён за узлом с меткой `matchlab.io/storage=true`; Redis не имеет постоянного тома.

Образы backend и Scalar приватны в GHCR. Все Deployment используют `imagePullSecrets: ghcr-pull`; registry credential имеет только `read:packages` и хранится в SOPS-зашифрованном Secret типа `kubernetes.io/dockerconfigjson`.

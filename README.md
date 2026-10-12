# MatchLab Infra

Kubernetes-манифесты и GitOps MatchLab на Flux CD и Kustomize. Код, Dockerfile, миграции и ручная сборка образов находятся в [matchlab-backend](https://github.com/HSE-Scientists-Team/matchlab-backend).

## Структура

- `clusters/homelab/` — Flux, namespace приложения и версии образов в `images.yaml`.
- `apps/secrets/` — Kubernetes Secret, зашифрованные SOPS/age; private key находится вне Git.
- `apps/platform/` — PostgreSQL и SeaweedFS S3 с локальными PVC, Redis.
- `apps/backend/` — четыре backend-сервиса, Scalar, ConfigMap и публичный Ingress Gateway.
- `.github/workflows/validate.yml` — проверка сборки Kustomize.

## GitOps

Успешная ручная сборка в backend может создать PR с digest выбранных образов. После слияния Flux обновляет соответствующие Deployment. Секреты расшифровывает Flux; платформенные сервисы зависят от Secret, backend — от готовности платформы. Все четыре backend-сервиса применяют общий SQL-набор перед открытием API под PostgreSQL advisory-блокировкой.

Несекретная конфигурация монтируется из ConfigMap, пароли передаются через ссылки `secretKeyRef`. Scalar доступен через `/docs/` на origin Gateway. PostgreSQL закреплён за узлом с меткой `matchlab.io/storage=true`; Redis не имеет постоянного тома.

Образы backend и Scalar приватны в GHCR. Все Deployment используют `imagePullSecrets: ghcr-pull`; registry credential имеет только `read:packages` и хранится в SOPS-зашифрованном Secret типа `kubernetes.io/dockerconfigjson`.

## S3

SeaweedFS предоставляет внутренний endpoint `http://seaweedfs:8333`, регион `us-east-1`, path-style bucket `matchlab-media`. StatefulSet хранит данные на отдельном PVC 50Gi с сохранением при удалении и масштабировании. Это одна реплика с локальным томом; для восстановления нужны резервные копии объектов и метаданных. S3, filer и административные интерфейсы не публикуются наружу.

`seaweedfs-init` идемпотентно создаёт приватный bucket и CORS для `https://api.matchlab.space`. IAM-политика разрешает ключам Media чтение, запись, удаление и multipart только в этом bucket. Администраторские ключи используются хранилищем и init-джобой; выдавать их Media не требуется.

Secret `matchlab-s3` зашифрован SOPS: `admin-access-key`, `admin-secret-key`, `media-access-key`, `media-secret-key`. Для будущего Deployment Media последние два ключа передаются через `secretKeyRef` в `S3_MEDIA_ACCESS_KEY` и `S3_MEDIA_SECRET_KEY`; пароль БД — из `matchlab-postgres`. Несекретные настройки Media должны монтироваться из ConfigMap. `MEDIA_IMAGE` зарезервирован для CI, Deployment Media пока не активирован.

Для клиентских подписанных URL при выпуске Media нужен отдельный доступный клиентам HTTPS S3 endpoint, согласованный `s3.public_endpoint`, DNS/TLS и CORS frontend-origin. Внутренний DNS `seaweedfs` клиентам недоступен. Изменения CORS или шаблона init-джобы пересоздают Job через Flux force; завершённая Job остаётся в GitOps. Ротация S3-ключей требует согласованного обновления Secret и перезапуска SeaweedFS и Media.

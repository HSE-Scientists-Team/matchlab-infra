# MatchLab Infra

Kubernetes-манифесты и GitOps MatchLab на Flux CD и Kustomize. Код, Dockerfile, миграции и ручная сборка образов находятся в [matchlab-backend](https://github.com/HSE-Scientists-Team/matchlab-backend).

## Структура

- `clusters/homelab/` — Flux, namespace приложения и версии образов в `images.yaml`.
- `apps/secrets/` — Kubernetes Secret, зашифрованные SOPS/age; private key находится вне Git.
- `apps/platform/` — PostgreSQL и SeaweedFS S3 с локальными PVC, Redis.
- `apps/backend/` — шесть backend-сервисов, Scalar, ConfigMap и публичный Ingress Gateway.
- `.github/workflows/validate.yml` — проверка сборки Kustomize.

## GitOps

Успешная ручная сборка в backend может создать PR с digest выбранных образов. После слияния Flux обновляет соответствующие Deployment. Секреты расшифровывает Flux; платформенные сервисы зависят от Secret, backend — от готовности платформы. Все шесть backend-сервисов применяют общий SQL-набор перед открытием API под PostgreSQL advisory-блокировкой.

Несекретная конфигурация монтируется из ConfigMap, пароли передаются через ссылки `secretKeyRef`. Scalar доступен через `/docs/` на origin Gateway. PostgreSQL закреплён за узлом с меткой `matchlab.io/storage=true`; Redis не имеет постоянного тома.

Образы backend и Scalar приватны в GHCR. Все Deployment используют `imagePullSecrets: ghcr-pull`; registry credential имеет только `read:packages` и хранится в SOPS-зашифрованном Secret типа `kubernetes.io/dockerconfigjson`.

## S3

SeaweedFS предоставляет внутренний endpoint `http://seaweedfs:8333`, регион `us-east-1`, path-style bucket `matchlab-media`. StatefulSet хранит данные на отдельном PVC 10Gi с сохранением при удалении и масштабировании. Это одна реплика с локальным томом; для восстановления нужны резервные копии объектов и метаданных. Traefik публикует только S3-путь bucket `/matchlab-media` на `https://api.matchlab.space`, без переписывания пути или Host: это сохраняет подпись SigV4. Filer и административные интерфейсы остаются внутренними. Bucket приватный: клиент использует подписанные ссылки Media.

`seaweedfs-init` идемпотентно создаёт приватный bucket и CORS для `https://api.matchlab.space`. IAM-политика разрешает ключам Media чтение, запись, удаление и multipart только в этом bucket. Администраторские ключи используются хранилищем и init-джобой; выдавать их Media не требуется.

Secret `matchlab-s3` зашифрован SOPS: `admin-access-key`, `admin-secret-key`, `media-access-key`, `media-secret-key`. В Deployment Media последние два ключа передаются через `secretKeyRef` в `S3_MEDIA_ACCESS_KEY` и `S3_MEDIA_SECRET_KEY`; пароль БД — из `matchlab-postgres`. Несекретные настройки Media монтируются из ConfigMap. Digest `MEDIA_IMAGE` обновляется CI; Gateway подключается к внутреннему gRPC Service `media:8085`.

Для клиентских подписанных URL `s3.public_endpoint` задан как `https://api.matchlab.space`; path-style SDK добавляет имя bucket к пути. Внутренние запросы Media используют `http://seaweedfs:8333`. Для нового frontend-origin нужно обновить CORS bucket. Изменения CORS или шаблона init-джобы пересоздают Job через Flux force; завершённая Job остаётся в GitOps. Ротация S3-ключей требует согласованного обновления Secret и перезапуска SeaweedFS и Media.

## HTTPS

`apps/cert-manager` устанавливает официальный Helm chart cert-manager v1.21.2 через Flux. CRD сохраняются при удалении Helm release. `apps/tls` объявляет Issuer Let’s Encrypt production и Certificate для `api.matchlab.space`; приватные ключи аккаунта и сертификата создаёт контроллер в Kubernetes Secret и в Git они не попадают. Сертификат автоматически продлевается, приватный ключ ротируется.

DNS A-запись домена должна вести на публичный адрес ingress. TCP 80 нужен для HTTP-01 challenge и редиректа, TCP 443 — для HTTPS. Certificate готовится после cert-manager; backend зависит от готовности TLS. Traefik обслуживает API и Scalar по HTTPS, отдельный HTTP Ingress перенаправляет на HTTPS. Временный Ingress cert-manager для `/.well-known/acme-challenge/` не наследует middleware редиректа.

Документация доступна по `https://api.matchlab.space/docs/`, проверка API — `https://api.matchlab.space/health`. CORS и API-запросы Scalar работают на том же origin. При смене домена нужно согласованно обновить DNS, Certificate, Ingress и связанные конфигурации.

## Support

Support создаёт жалобы через внутренний gRPC Service `support:8086`, проверяет вложения через `media:8085` и хранит жалобы в PostgreSQL. Gateway получает адрес Support из ConfigMap; пароль PostgreSQL передаётся через `matchlab-postgres`. `SUPPORT_IMAGE` обновляется CI вместе с остальными digest. Для HTTP-маршрута жалоб нужно выпустить Gateway и Scalar из версии backend с Support. Внешние порты для gRPC не открываются.

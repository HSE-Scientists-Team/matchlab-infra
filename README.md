# MatchLab Infra

Kubernetes-манифесты и GitOps MatchLab на Flux CD и Kustomize. Код, Dockerfile, миграции и ручная сборка образов находятся в [matchlab-backend](https://github.com/HSE-Scientists-Team/matchlab-backend).

## Структура

- `clusters/homelab/` — Flux, namespace приложения и версии образов в `images.yaml`.
- `apps/secrets/` — Kubernetes Secret, зашифрованные SOPS/age; private key находится вне Git.
- `apps/platform/` — PostgreSQL и SeaweedFS S3 с локальными PVC, Redis.
- `apps/backend/` — одиннадцать backend-сервисов, frontend, Scalar, ConfigMap и публичный Ingress Gateway.
- `.github/workflows/validate.yml` — проверка сборки Kustomize.

## GitOps

Успешная ручная сборка в backend может создать PR с digest выбранных образов. После слияния Flux обновляет соответствующие Deployment. Секреты расшифровывает Flux; платформенные сервисы зависят от Secret, backend — от готовности платформы. Все одиннадцать backend-сервисов применяют общий SQL-набор перед открытием API под PostgreSQL advisory-блокировкой.

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

## Проекты, поиск и рекомендации

Project (`project:8087`) хранит проекты, роли, участников, заявки и приглашения. Search (`search:8088`) обращается к User и Project; Recommendation (`recommendation:8089`) использует User и Search для случайных рекомендаций людей и проектов. Gateway получает внутренние адреса из ConfigMap; наружу доступен только HTTP API Gateway. Привилегированные RPC владельцев данных доступны через административный фасад Admin.

Все три сервиса получают пароль PostgreSQL через `matchlab-postgres`, в том числе для общих миграций. Project передаёт состав и состояние проектов в User через outbox. Одинаковый `PROJECT_SYNC_TOKEN` поступает в оба Deployment из SOPS Secret `matchlab-project-sync`, ключ `token`. При ротации нужно обновить Secret и перезапустить оба Deployment; outbox повторяет временно неудачные доставки.

Релиз KAN-39 включает миграцию `00006`: обновляйте весь набор Go-образов вместе, поскольку старые бинарники не распознают новую историю миграций при перезапуске. Scalar также обновляется для новых HTTP-маршрутов. Версии образов закреплены digest в `clusters/homelab/images.yaml`.

## Мониторинг (KAN-60)

`apps/monitoring` содержит один Prometheus, Grafana, node-exporter на каждой ВМ и kube-state-metrics. Prometheus сам собирает метрики без дополнительного оператора. cAdvisor/kubelet дают CPU, RAM и доступные runtime/volume-метрики контейнеров; node-exporter — CPU, RAM, файловые системы, дисковый и сетевой ввод-вывод каждой ВМ. kube-state-metrics показывает состояние подов, рестарты, requests/limits, образ и digest. Go-сервисы экспортируют внутренний `:9090/metrics`: запросы/коды/задержки/активные запросы, Go/process, SQL-пулы и `matchlab_build_info` с revision. Внешние порты для метрик не открываются. Сборщик использует read-only API-доступ; `nodes/proxy` нужен для cAdvisor через проверенный TLS API server и является привилегированным правом, этот service account нельзя передавать приложениям.

Prometheus выбран из-за встроенных ограничений retention по времени и объёму. Настройки: 30 секунд, 7 дней, `retention.size=6GB`, WAL compression, короткие блоки 2 часа, sample limits и фильтрация метрик. PVC запрашивает 10Gi; Grafana имеет отдельный PVC 1Gi для SQLite, пользователей, настроек и ручных дашбордов. Срок хранения — окно TSDB с очисткой целых блоков, а не точное уничтожение каждого sample в момент достижения 7 дней. При достижении бюджета старые блоки удаляются раньше семи дней.

**Жёсткий лимит хранилища:** Prometheus использует отдельную ext4-файловую систему не более 10GiB, смонтированный в `/var/lib/matchlab-metrics` на единственном узле с меткой `matchlab.io/metrics-disk=ready`. Static PV и StorageClass `matchlab-metrics-local` не используют local-path: размер ограничивает сама файловая система. `scripts/prepare-metrics-volume.sh` выделяет файл фиксированного размера 10GiB на существующем диске (fallocate), создаёт ext4 и монтирует его через loop. Скрипт требует минимум 20GiB свободного места перед выделением, чтобы оставить запас системному разделу; существующий файл никогда не переформатируется. Это не требует нового устройства или переразметки. Альтернатива для отдельного виртуального диска — `scripts/prepare-metrics-disk.sh`: проверяет размер и пустоту устройства, форматирование возможно только с явным `--format-blank`. Метку узла выставляют после успешной проверки диска. Без метки pod остаётся Pending и не использует системный раздел. Том должен монтироваться через fstab при каждом запуске узла до запуска k3s; скрипт добавляет `RequiresMountsFor` для k3s, чтобы при отказе диска узел не стартовал с пустым каталогом на системном разделе.

`retention.size` не является точным лимитом TSDB: WAL/head и временная компактация требуют запаса. Здесь 6Gi отведены retention и остальное оставлено под эти расходы; контроль TSDB-бюджета начинается с 8Gi. При заполнении физического диска новые записи прекращаются, вместо роста в системном разделе. Volume stats могут отсутствовать у локального PV, а container filesystem stats зависят от runtime; свободное место отдельного диска дополнительно собирает node-exporter. Единственная реплика и локальные тома не обеспечивают HA. Grafana по-прежнему использует local-path, её 1Gi PVC не является физической квотой.


Grafana доступна на `https://api.matchlab.space/grafana/` через существующий сертификат. Анонимный вход и самостоятельная регистрация отключены. Начальные `username`/`password` находятся в SOPS Secret `matchlab-grafana`; эти переменные инициализируют admin только при создании БД Grafana. Дальнейшая смена пароля выполняется в Grafana; простая ротация Secret не меняет пароль существующей SQLite-БД. Prometheus и exporters доступны внутри кластера, ingress ограничен NetworkPolicy до Prometheus/Grafana; node-exporter читает host mounts только read-only.

Готовые дашборды: **Application**, **Services and releases**, **Virtual machines**, **Monitoring health**. Они генерируются командой `python3 scripts/generate-dashboards.py`, JSON хранится в `apps/monitoring/dashboards`, проверка воспроизводимости — `--check`. Изменения ConfigMap приводят к обновлению пода Grafana, файловый provider синхронизирует папку **MatchLab GitOps**. Эта папка управляется Git: редактируйте генератор и пересоздавайте JSON. Свои дашборды создавайте в других папках через UI; копию GitOps-дашборда можно сохранить с новым UID через Save as. Они хранятся в PVC и не перезаписываются файловым provider. Резервное копирование Grafana должно включать её SQLite-БД; ручные дашборды автоматически в Git не экспортируются.

Начальные alert rules покрывают недоступность targets/Deployment, HTTP 5xx, OOM, нехватку RAM/диска ВМ и TSDB-бюджет. Их состояния видны в **Monitoring health**; отправка уведомлений не настроена (Alertmanager/contact points отсутствуют). Это дополнение к Zabbix. Новые сервисы добавляйте в scrape allowlist, выставляйте именованный container port `metrics` и настройки `metrics.address`; новые бинарники необходимо собрать до появления метрик.

Grafana запрашивает 256Mi RAM, лимит контейнера — 1Gi. `GOMEMLIMIT=768MiB` задаёт мягкий бюджет управляемой Go-памяти с запасом для остальной памяти процесса. Это не жёсткий предел RSS и не замена контейнерному лимиту. Проверять потребление следует при открытии и обновлении дашбордов. Alert `ContainerMemoryNearLimit` показывает превышение 85% лимита в течение пяти минут; `ContainerOOMKilled` учитывает новые рестарты за последние десять минут, а не бессрочно сохранённую причину завершения.

## Admin (KAN-35)

Admin (admin:8090) предоставляет служебную авторизацию и административные HTTP-операции через Gateway под /api/v1/admin. Служебные аккаунты и сеансы отделены от публичных пользователей. User, Support и Project проверяют короткоживущую подпись Admin; gRPC остаётся внутренним. Первый администратор создаётся один раз бинарником /admin-bootstrap из образа Admin. Права, ручки и bootstrap описаны в [документации backend](https://github.com/HSE-Scientists-Team/matchlab-backend/blob/master/cmd/admin/README.md). Начального пароля в Git нет.

SOPS Secret matchlab-admin-signing содержит seed, доступный только Admin через ADMIN_SIGNING_KEY. Отдельный SOPS Secret matchlab-admin-verification содержит public-key, который получают User, Support и Project через ADMIN_PUBLIC_KEY. Используются существующий age recipient и дешифрование Flux. Ротация требует согласованного обновления Secret и перезапуска четырёх потребителей. Известный тестовый ключ Compose в рабочем окружении не используется. Пароль bootstrap передаётся оператором временно и не добавляется в Secret ключей подписи.

Миграция 00007 общая для десяти Go-сервисов. Выпускайте все одиннадцать образов backend и Scalar вместе, с digest в clusters/homelab/images.yaml. Backend явно зависит от reconciliation секретов. Prometheus находит Admin по именованному порту metrics и списку разрешённых сервисов; существующие дашборды сервисов и версий включают его автоматически.

## Frontend (KAN-61)

React-админка доступна по https://api.matchlab.space/admin/. Ingress направляет префикс /admin в Service frontend:8080 без переписывания пути; /api остаётся на Gateway, /docs — на Scalar. Используется существующий TLS-сертификат. Прямые ссылки на карточки обрабатывает SPA fallback внутри Nginx.

Deployment использует приватный образ из matchlab-frontend, закреплённый FRONTEND_IMAGE в clusters/homelab/images.yaml, и существующий imagePullSecret ghcr-pull. Nginx работает от UID 101 с read-only root filesystem, отдельными emptyDir для /tmp и /etc/nginx/conf.d, без API-токена Kubernetes. Probe /healthz проверяет статический сервер. Frontend не выполняет SQL-миграции и не получает паролей или ключей Admin.

Для следующего релиза запустите Actions → Build frontend image в matchlab-frontend на master, оставив propose_deploy включённым. После проверок workflow публикует образ и создаёт infra PR только с FRONTEND_IMAGE. После его слияния Flux выполняет rollout. Пересобирать backend при изменениях frontend не требуется. Первичная настройка INFRA_REPO_TOKEN описана в README frontend.

CPU, RAM, рестарты и image digest frontend доступны в существующем дашборде Services and releases через kube-state-metrics/cAdvisor. Сам Nginx не экспортирует Go-метрики и в scrape allowlist Go-сервисов не добавляется.

## Chat (KAN-37)

Chat (`chat:8091`) предоставляет личные текстовые диалоги через Gateway под `/api/v1/chat`. gRPC остаётся внутренним. Сервис проверяет сеанс и блокировки через User, владеет схемой PostgreSQL `chat` и получает пароль БД из существующего Secret `matchlab-postgres`. Дополнительных секретов или внешних портов не требуется.

Релиз включает общую миграцию `00008`: необходимо собрать и обновить все одиннадцать Go-сервисов и Scalar из одной версии backend. Старые бинарники не распознают новую историю миграций при перезапуске. `CHAT_IMAGE` и остальные версии закреплены digest в `clusters/homelab/images.yaml`; frontend обновляется независимо. Перед выпуском сохраняйте резервную копию PostgreSQL; откат образов на версию без миграции 00008 после её применения невозможен без согласованного восстановления БД.

Prometheus обнаруживает Chat по именованному порту `metrics`; существующие дашборды показывают его запросы, версии и ресурсы автоматически. Health probes используют внутренний gRPC health endpoint.


## Домены и Android App Links

`matchlab.space` обслуживает админку `/admin/`, Grafana `/grafana/` и закрытые интерфейсы Airflow/Superset. Их скрытые пути остаются зашифрованы SOPS; меняется только origin. Прежние адреса интерфейсов на `api.matchlab.space` перенаправляются на основной домен с сохранением пути и query. Сеансы браузера привязаны к origin, поэтому после переноса может потребоваться повторный вход.

`api.matchlab.space` остаётся основным адресом Gateway, файлового S3 API и Scalar `/docs/`. Для админки сохранён same-origin фасад `/api/v1/admin` на основном домене; остальные пользовательские API вызываются по API-домену. Ссылка `/docs/` на основном домене перенаправляет к Scalar на API-домене.

Отдельный сертификат `matchlab-web` покрывает основной домен и не изменяет действующий API-сертификат. Письма сохраняют HTTPS-ссылку `/verify-email?token=…` на основном домене. Frontend-образ раздаёт страницу подтверждения с явной кнопкой и `/.well-known/assetlinks.json` без редиректа. Файл связывает Android-пакет с предоставленным сертификатом подписи; Android решает открывать установленное приложение по его intent-filter. Проверка на реальном телефоне выполняется отдельно от серверной проверки HTTPS/JSON. Для iOS нужны Team ID и окончательный bundle ID.

CORS S3 разрешает оба origin. Job `seaweedfs-init-web-origin` повторяет безопасную настройку существующего бакета и CORS; PVC и объекты сохраняются. Новый frontend digest выкатывается вместе с маршрутизацией. Параметры Airflow/Superset обновляются в зашифрованном `ml-ui` и применяются при перезапуске их Pod.

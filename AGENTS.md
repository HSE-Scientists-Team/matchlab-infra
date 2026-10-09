# MatchLab Infra

Этот репозиторий владеет Kubernetes-манифестами и GitOps для k3s. Код сервисов, Dockerfile и SQL-миграции находятся в matchlab-backend.

Используйте Flux CD и Kustomize. Новые окружения оформляйте отдельно в clusters/. Не коммитьте kubeconfig, пароли, PAT, SSH-ключи и plaintext Secret. Секреты создаются вне Git или хранятся через SOPS после настройки дешифрования.

Проверяйте манифесты через kubectl kustomize. Изменения PostgreSQL PVC, namespace и хранилища требуют внимания к сохранению данных. Все четыре backend-сервиса выполняют весь SQL-набор до открытия API с общей session advisory-блокировкой PostgreSQL. Отдельной Job миграций нет; сохраняйте PostgreSQL-конфигурацию и secret reference для каждого сервиса. Версии образов задаются отдельно в clusters/homelab/images.yaml; для релизов используйте digest, без latest. SOPS Secret находятся в apps/secrets, ключ дешифрования — в Secret sops-age namespace flux-system; не добавляйте private age key в Git. Не запускайте bootstrap или применение манифестов в живом кластере без просьбы пользователя.

Репозиторий публичный. Не добавляйте одноразовые гайды установки, отчёты о состоянии узлов, SSH-логины, частные IP, локальные пути и сведения о физической инфраструктуре. README описывает структуру и назначение манифестов.

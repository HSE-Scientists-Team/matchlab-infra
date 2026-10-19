# ML / BI for the k3s pilot

This private pilot is managed by `clusters/homelab/ml-release.yaml`.
Airflow starts with its DAG paused; run and validate the first real batch before
enabling its schedule. Validate with `kubectl kustomize apps/ml` and
`kubectl kustomize apps/backend-ml`.

It supplies a separate metadata/analytics PostgreSQL, recommendation-only Redis,
MLflow, Airflow LocalExecutor and provisioned Superset. PVCs use the cluster's
default StorageClass; one replica and Recreate support single-node RWO storage.
This is a pilot configuration, without HA or a tested capacity guarantee.
Redis is disposable, noeviction; it never shares Auth's Redis. Go falls back to
live Search when this cache is unavailable.

All services are ClusterIP. There is no Ingress and no unauthenticated public
tracking endpoint. Access private UIs with an authorized Kubernetes port-forward
(over its authenticated encrypted API connection); keep localhost binding.
Airflow and Superset also require their generated operator accounts. MLflow has
no app authentication: its NetworkPolicy accepts only Airflow / `app=ml-batch`
clients. Verify policy enforcement by the cluster CNI before activation. Public
UI exposure requires a separately reviewed TLS/auth proxy; changing Service type
is insufficient. Superset's HTTP cookie setting is for localhost forwarding.
Do not give ordinary product users the Superset bootstrap Admin account: provision
read-only BI roles for their dashboards before onboarding them.

## Required external configuration

No Secret values are stored here. Provision these Secrets through the existing
secret-management process in the target namespace; passwords used in URLs must
be URL encoded (hex-generated passwords are convenient). Keep credentials aligned;
provisioning intentionally does not silently rotate existing roles.

| Secret | Required keys |
| --- | --- |
| `matchlab-ml-db-admin` | `password`, `url` (admin DSN to ml-db / postgres database) |
| `matchlab-ml-provision` | `source-password`, `analytics-password`, `bi-password`, `airflow-password`, `superset-password` |
| `matchlab-ml-runtime` | `source-url` (ml_reader), `analytics-url` (analytics_writer), `redis-url` |
| `matchlab-recommendation-redis` | `password` |
| `matchlab-airflow` | `metadata-url` (airflow DB, SQLAlchemy psycopg2), `fernet-key`, `jwt-secret`, `admin-password` |
| `matchlab-superset` | `metadata-url` (superset DB), `analytics-url` (analytics_reader, SQLAlchemy psycopg2), `secret-key`, `admin-password` |

Existing `matchlab-postgres/password` and `ghcr-pull` are reused. Only the short-lived
provisioning Job receives business DB admin credentials. Online Recommendation
receives only its Redis password. Batch uses SELECT on the six owner views; BI
uses SELECT on aggregate views only. Superuser credentials never enter Airflow tasks.

`matchlab-images` in flux-system must contain CI-produced `ML_IMAGE`,
`AIRFLOW_IMAGE`, and `MLFLOW_IMAGE` digests. Supply a separate ConfigMap `matchlab-ml-images` there
with `SUPERSET_IMAGE` and `ML_CODE_VERSION`. All image substitutions must
be real reviewed `repository@sha256:...` digests, never fabricated placeholders.
Superset is built by `.github/workflows/build-ml-bi.yml`; ML/Airflow/MLflow by backend's
build-images workflow. PostgreSQL and Redis are pinned to the upstream image digests resolved during local
validation. Review dependency
and image vulnerability reports at that time; availability is not a security audit.

## Release sequence and recovery

1. Pass local Go/integration/Compose/API checks. Back up the business DB, analytics
   and metadata DBs, MLflow volume and artifacts; perform a restore rehearsal into
   isolated storage. Backups must use restricted access and encryption.
2. Build **all eleven Go services** plus ML/Airflow/MLflow and Superset. Coordinate migration
   00009 after Chat's 00008; an older Go image will reject an unknown SQL version.
   Keep existing backend config until migrations and ML checks succeed.
3. Review SOPS secrets, real image digests, storage capacity and NetworkPolicy. Render
   all bases before merging the GitOps release.
4. After activation, provision roles/DBs with `ml-provision-v1`,
   then Superset with `superset-provision-v1`. Jobs wait for their databases and export views. The two idempotent provisioning
   Jobs use per-resource Flux force recreation when their pod template changes;
   this reruns provisioning after an image update without deleting any PVC.
   Completed Jobs remain until the next provisioning release.
5. Keep the Airflow DAG paused. Trigger a manual run and validate export grants,
   analytics counts, tracking artifacts and Redis publication. Test with actual local
   accounts, blocks, full/closed projects and a recommendation-Redis outage.
6. The backend Flux path `./apps/backend-ml` is part of the reviewed release,
   preserving image substitutions/dependencies. It adds the Redis peer and secret.
   After validation, unpause the six-hour DAG. Do not create a Flux dependency cycle:
   ML depends on backend's owner views; backend can start with Redis unavailable.

Rollback the selected algorithm by setting `ML_MODEL=baseline` and starting a new
run. To disable cache serving, restore backend's `./apps/backend` path; Search
continues serving recommendations. Pause scheduling while diagnosing failures.
Do not roll back business migrations or delete PVCs as an algorithm rollback.
`prune: false` deliberately protects stateful resources during this pilot; explicit
resource removal and PVC disposal require a separate reviewed operation.

## Data lifecycle and operations

Snapshots contain free text and stable IDs, so they are restricted personal data,
not anonymous exports. Pilot retention target: raw runs 7 days, minimized analytics history 30 days;
backups 30 days with a deletion ledger for any restore.
Use the explicit `python -m matchlab_ml.maintenance` command from the ML image to
preview cleanup, then `--apply` during a maintenance window with the DAG paused.
It preserves the active Redis generation and the latest completed analytics run,
even if refresh has stalled beyond those windows. Freshness alerts require an
operator to resolve such exceptions; an absolute erasure deadline needs explicit
operator disposal of the protected snapshots as well.
For a deletion request, invalidate recommendations, purge affected historical
artifacts/analytics with an authorized operator, then generate a fresh source run.
The source excludes deleted users and live owner APIs enforce visibility immediately;
historical retained exports need this separate deletion process. Do not treat a
scheduled refresh as complete historical erasure.

Back up metadata with DB-consistent dumps and MLflow SQLite with its backup API or
while stopped; filesystem copies of a live SQLite DB are not a backup procedure.
Keep artifact volume and tracking DB restore points aligned. Restore first into an
isolated namespace, validate counts/grants, and leave scheduling paused until reviewed.

The hourly `ml-freshness` CronJob runs `python -m matchlab_ml.maintenance --check-freshness`.
It exits nonzero for no
completed PostgreSQL run, source older than 12 hours, missing/expired published cache
for nonempty source, or an excessively old cache. The Prometheus rule `RecommendationFreshnessCheckFailed` observes failed Jobs via
kube-state-metrics. Verify alert delivery before enabling scheduled serving; the
existing monitoring configuration owns the notification destination.
Watch PVC capacity, failed Jobs, memory limits and DAG failures. Retention removes
application artifacts/analytics only; MLflow's sanitized metadata/backups need their
own age-based operator policy. No latency or ranking quality SLO is claimed yet.

### Dependency review gate

The upstream MLflow 3.5.1 image failed the vulnerability review and has been replaced
locally by 3.17.1, with its client pinned to the same release. Superset uses 6.1.0
with OS updates and compatible security patches; image builds run dependency checks.
This does **not** establish a clean vulnerability scan. Superset still constrains
some libraries (notably `pyarrow<19`, `cryptography<47`, `msgpack<1.1`), so blindly
forcing every scanner-proposed major upgrade would break the supported environment.
Review the final image scan and any upstream exceptions before real-user activation;
keeping this pilot private is an access boundary, not a vulnerability fix. Rebuild
and rescan images periodically, including their OS libraries.

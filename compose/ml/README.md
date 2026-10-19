# Local ML and product analytics components

This directory owns the local Compose overlay, Airflow DAG and Superset assets.
Python models and service Dockerfiles belong to the backend repository (`ml/`).
The overlay is merged with that checkout's Compose file, not a second business
database. No resource in this directory is included in Flux/Kustomize.

- `stack.py`: prepares private ignored local configuration and invokes Compose;
  supports either the Docker Compose v2 plugin or standalone v2 binary.
- `compose.yaml`: isolated local project, batch image, Airflow, patched MLflow, Superset,
  separate Redis and PostgreSQL metadata/analytics databases.
- `init_databases.py`: local provisioning only; grants the source reader SELECT
  on six versioned owner export views, BI reader on twelve aggregate views.
- `dags/`: one six-hour DAG, no catchup, one active run, bounded retries.
- `superset/dashboards.json`: four managed dashboards, fifteen charts.
- `superset/bootstrap.py`: idempotent provisioning for pinned Superset 6.1 ORM;
  never deletes unrelated dashboards. Changes to managed charts are reapplied.
- `tests/`: dependency-free launcher/layout/definition tests.

All published ML/BI ports bind to loopback. MLflow has no user authentication in
this local setup; do not expose it through an ingress. Airflow's simple auth and
`standalone` process are for local use. A production deployment needs a separate
review of TLS, authentication, role grants, backups, retention, image digests,
resource sizing and NetworkPolicy. This is not a production Helm distribution.

## Validation

Run `python3 stack.py init --backend PATH`, `config`, `up`, `batch`, `smoke`,
`airflow-check`, and `airflow-run` in that order. `airflow-check` checks DAG imports;
`airflow-run` executes the complete DAG manually, without enabling its schedule.
`python3 stack.py e2e` explicitly creates local accounts, confirms email through
Mailpit, creates projects, verifies personalized responses and live eligibility,
and temporarily stops only recommendation Redis to verify fallback. Test records
remain in the isolated local business volume, labelled `ML local test`.

The versioned Airflow image contains its DAG/startup entrypoint; the adjacent
backend copy and this directory's source definitions must be kept aligned.
For the disabled k3s pilot base and release prerequisites see `apps/ml/README.md`.

For an 8 GiB laptop, start with a 4 GiB Docker VM and run expensive checks one at a
time. The local pilot uses one Superset worker, one Airflow executor slot and one
DAG parser (120-second refresh), with a composite Airflow healthcheck. Pause heavy
UI/browser checks while executing DAG tests; a larger VM on an 8 GiB machine can
make the host swap heavily instead of helping. Go images share their common
compilation layer so a cold full build does not repeat it for every service.

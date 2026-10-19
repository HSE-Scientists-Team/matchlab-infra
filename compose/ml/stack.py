"""Local-only Compose launcher. No host paths or generated secrets in Git."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys


STACK = Path(__file__).resolve().parent
LOCAL = STACK / ".local"
ENV = LOCAL / ".env"


def initialize(backend):
    backend = Path(backend).resolve()
    if not (backend / "ml" / "pyproject.toml").is_file():
        raise SystemExit("--backend must point to the backend checkout containing the new ml package")
    if ENV.exists():
        raise SystemExit("Local configuration already exists; preserving its credentials and database volumes")
    LOCAL.mkdir(mode=0o700, parents=True, exist_ok=True)
    values = {"ML_BACKEND_DIR": str(backend), "ML_STACK_DIR": str(STACK), "ML_MODEL": "baseline",
              "POSTGRES_USER": "matchlab", "POSTGRES_DB": "matchlab",
              "POSTGRES_PORT": "127.0.0.1:5432", "REDIS_PORT": "127.0.0.1:6379",
              "GATEWAY_PORT": "127.0.0.1:8080"}
    for name in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "PROJECT_SYNC_TOKEN", "ML_DB_ADMIN_PASSWORD",
                 "ML_SOURCE_PASSWORD", "ML_ANALYTICS_PASSWORD", "ML_BI_PASSWORD", "ML_AIRFLOW_PASSWORD",
                 "ML_SUPERSET_DB_PASSWORD", "ML_REDIS_PASSWORD", "ML_SUPERSET_SECRET_KEY",
                 "ML_SUPERSET_ADMIN_PASSWORD", "ML_AIRFLOW_ADMIN_PASSWORD", "ML_AIRFLOW_JWT_SECRET"):
        values[name] = secrets.token_hex(32)
    values["ML_AIRFLOW_FERNET_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    if any("'" in value or "\n" in value for value in values.values()):
        raise SystemExit("Unsupported quote/newline in a checkout path")
    # A new project name means existing developer Compose volumes are not reused.
    with ENV.open("x", encoding="utf-8") as stream:
        os.chmod(ENV, 0o600)
        stream.write("\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n")
    password_file = LOCAL / "airflow-passwords.json"
    with password_file.open("x", encoding="utf-8") as stream:
        os.chmod(password_file, 0o600)
        json.dump({"analyst": values["ML_AIRFLOW_ADMIN_PASSWORD"]}, stream)
    print("Created ignored .local/.env and Airflow password file. Keep both private.")
    print("Docker has not been started. Next: python3 stack.py config")


def compose(arguments):
    if not ENV.exists():
        raise SystemExit("First run: python3 stack.py init --backend PATH_TO_BACKEND")
    values = dict(line.rstrip().split("=", 1) for line in ENV.read_text().splitlines() if line and not line.startswith("#"))
    backend = Path(values["ML_BACKEND_DIR"].strip("'"))
    docker = shutil.which("docker")
    standalone = shutil.which("docker-compose")
    if docker and subprocess.run([docker, "compose", "version"], capture_output=True).returncode == 0:
        command = [docker, "compose"]
    elif standalone:
        command = [standalone]
    else:
        raise SystemExit("Install Docker Compose v2 (or start Docker Desktop, which includes it)")
    # Shell environment otherwise silently overrides --env-file. Use only this
    # project file for its keys; unrelated host settings (Docker context) remain.
    environment = {key: value for key, value in os.environ.items() if key not in values}
    environment.setdefault("COMPOSE_PARALLEL_LIMIT", "2")
    command += ["--project-name", "matchlab-ml-local", "--env-file", str(ENV),
                "-f", str(backend / "compose.yaml"), "-f", str(STACK / "compose.yaml")]
    return subprocess.call(command + arguments, env=environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "config", "up", "build", "ps", "logs", "down", "batch", "demo-analytics", "airflow-check", "airflow-run", "smoke", "e2e"])
    parser.add_argument("--backend")
    args = parser.parse_args()
    if args.action == "init":
        if not args.backend:
            parser.error("init requires --backend")
        initialize(args.backend)
        return 0
    if args.action == "e2e":
        return subprocess.call([sys.executable, str(STACK / "e2e.py")])
    commands = {"config": ["config", "--quiet"], "up": ["up", "--build", "-d"],
                "build": ["build"], "ps": ["ps", "-a"], "logs": ["logs", "--tail", "100"],
                "down": ["down"],  # Deliberately retain all named data volumes.
                "batch": ["run", "--rm", "ml-batch"],
                "demo-analytics": ["run", "--rm", "ml-batch", "--source", "demo", "--analytics-only"],
                "airflow-check": ["exec", "airflow", "airflow", "dags", "list-import-errors"],
                "airflow-run": ["exec", "airflow", "env", "-u", "ML_AIRFLOW_ADMIN_PASSWORD", "airflow", "dags", "test", "matchlab_recommendations"],
                "smoke": ["run", "--rm", "--entrypoint", "python", "ml-batch", "/app/ml/smoke.py"]}
    return compose(commands[args.action])


if __name__ == "__main__":
    sys.exit(main())

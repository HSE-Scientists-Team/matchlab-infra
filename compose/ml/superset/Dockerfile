FROM apache/superset:6.1.0
USER root
# Refresh security patches in the upstream OS; retain Superset's dependency bounds.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN . /app/.venv/bin/activate && uv pip install --no-cache \
    psycopg2-binary==2.9.10 PyJWT==2.14.0 Mako==1.3.12 Brotli==1.2.0 \
    Pillow==12.3.0 pyasn1==0.6.4 urllib3==2.8.0 cryptography==46.0.5 pyOpenSSL==26.0.0 \
    && uv pip check
COPY --chown=superset:superset . /app/bootstrap/
USER superset
ENV SUPERSET_CONFIG_PATH=/app/bootstrap/superset_config.py

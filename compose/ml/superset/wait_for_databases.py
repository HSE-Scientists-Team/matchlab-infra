"""Wait for provisioned metadata and read-only analytics, without logging DSNs."""
import os
import time

def wait_for_databases(attempts=120, sleep=time.sleep, probe=None):
    if probe is None:
        from sqlalchemy import create_engine, text
        def probe():
            for key, query in [("SUPERSET_METADATA_URL", "SELECT 1"),
                               ("SUPERSET_ANALYTICS_URL", "SELECT 1 FROM analytics.overview LIMIT 1")]:
                engine = create_engine(os.environ[key], connect_args={"connect_timeout": 5})
                try:
                    with engine.connect() as connection:
                        connection.execute(text(query))
                finally:
                    engine.dispose()
    for attempt in range(attempts):
        try:
            probe()
            return
        except Exception:
            if attempt + 1 == attempts:
                raise RuntimeError("Provisioned databases did not become ready; credentials omitted") from None
            sleep(5)

if __name__ == "__main__":
    wait_for_databases()

"""Honor HTTPS forwarding at Airflow's supported ASGI extension point.

The UI NetworkPolicy admits only Traefik to this Pod. Traefik validates external
forwarding headers; localhost execution API calls without headers stay HTTP.
"""
from airflow.plugins_manager import AirflowPlugin
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


class MatchLabProxyHeaders(AirflowPlugin):
    name = "matchlab_proxy_headers"
    fastapi_root_middlewares = [
        {
            "name": "matchlab_https_proxy",
            "middleware": ProxyHeadersMiddleware,
            "args": [],
            "kwargs": {"trusted_hosts": "*"},
        }
    ]

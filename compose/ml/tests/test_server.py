"""Contracts of the opt-in server pilot; no cluster access."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ServerTests(unittest.TestCase):
    def test_server_is_enabled_with_private_interfaces(self):
        release = (ROOT / 'clusters/homelab/ml-release.yaml').read_text()
        self.assertIn('suspend: false', release)
        self.assertIn('ml-release.yaml', (ROOT / 'clusters/homelab/kustomization.yaml').read_text())
        resources = json.loads((ROOT / 'apps/ml/kustomization.yaml').read_text())['resources']
        for name in resources:
            resource = json.loads((ROOT / 'apps/ml' / name).read_text())
            self.assertNotEqual(resource['kind'], 'Ingress')
            if resource['kind'] == 'Service':
                self.assertEqual(resource['spec'].get('type', 'ClusterIP'), 'ClusterIP')
            if resource['kind'] in {'Job', 'Deployment', 'CronJob'}:
                workload = resource['spec']['jobTemplate'] if resource['kind'] == 'CronJob' else resource
                spec = workload['spec']['template']['spec']
                self.assertFalse(spec['automountServiceAccountToken'])
                self.assertTrue(spec['securityContext']['runAsNonRoot'])
                for container in spec['containers']:
                    self.assertNotIn(':latest', container['image'])
                    self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
                    secrets = [e['valueFrom']['secretKeyRef']['name'] for e in container.get('env', []) if 'valueFrom' in e]
                    if name != 'provision.json':
                        self.assertNotIn('matchlab-postgres', secrets)
                        self.assertNotIn('matchlab-ml-db-admin', secrets if name != 'database.json' else [])

    def test_freshness_alert_has_metrics_collection_and_read_only_rbac(self):
        self.assertIn('persistentvolumeclaims,jobs,cronjobs',
                      (ROOT / 'apps/monitoring/kube-state-metrics.yaml').read_text())
        rbac = (ROOT / 'apps/monitoring/rbac.yaml').read_text()
        self.assertIn('  - batch\n  resources:\n  - jobs\n  - cronjobs\n  verbs:\n  - list\n  - watch', rbac)
        self.assertIn('kube_job_failed', (ROOT / 'apps/monitoring/config/alerts.yml').read_text())

    def test_airflow_image_and_local_definitions_agree(self):
        backend = ROOT.parent / 'matchlab-backend'
        if not backend.exists():
            self.skipTest('adjacent backend checkout is optional in infra CI')
        for source, target in [('start_airflow.py', 'start_airflow.py'),
                               ('dags/matchlab_recommendations.py', 'matchlab_recommendations.py')]:
            self.assertEqual((ROOT / 'compose/ml' / source).read_text(),
                             (backend / 'ml/airflow' / target).read_text())

    def test_backend_overlay_enables_the_actual_redis_peer_contract(self):
        config = (ROOT / 'apps/backend-ml/recommendation.yaml').read_text()
        self.assertIn('  recommendation_redis: recommendation-redis:6379', config)
        self.assertNotIn('cache:', config)
        self.assertNotIn('recommendation_redis:', (ROOT / 'apps/backend/config/recommendation.yaml').read_text())

class RolloutTests(unittest.TestCase):
    def test_freshness_metric_survives_filter(self):
        import re
        text = (ROOT / 'apps/monitoring/config/prometheus.yml').read_text().split('- job_name: kube-state-metrics')[1].split('- job_name: cadvisor')[0]
        pattern = re.search(r'regex: (.+)', text)[1]
        self.assertIsNotNone(re.fullmatch(pattern, 'kube_job_failed'))
        self.assertIn('condition="true"', (ROOT / 'apps/monitoring/config/alerts.yml').read_text())

    def test_airflow_checks_component_health_and_recovers(self):
        obj = json.loads((ROOT / 'apps/ml/airflow.json').read_text())
        container = obj['spec']['template']['spec']['containers'][0]
        for key in ['startupProbe', 'readinessProbe', 'livenessProbe']:
            self.assertIn('matchlab_ml.health', container[key]['exec']['command'])

    def test_provision_jobs_can_be_replaced_without_touching_volumes(self):
        for name in ['provision.json', 'superset-init.json']:
            obj = json.loads((ROOT / 'apps/ml' / name).read_text())
            self.assertEqual(obj['metadata']['annotations']['kustomize.toolkit.fluxcd.io/force'], 'enabled')

    def test_superset_wait_retries_until_provisioning_is_complete(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('wait_databases', ROOT / 'compose/ml/superset/wait_for_databases.py')
        wait = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wait)
        from unittest.mock import Mock
        probe = Mock(side_effect=[RuntimeError('not ready'), None])
        sleep = Mock()
        wait.wait_for_databases(attempts=2, probe=probe, sleep=sleep)
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(5)
        with self.assertRaisesRegex(RuntimeError, 'credentials omitted'):
            wait.wait_for_databases(attempts=1, probe=Mock(side_effect=RuntimeError('secret dsn')))

class PublicUITests(unittest.TestCase):
    def test_public_routes_are_encrypted_and_do_not_replace_login(self):
        for name in ['ml-airflow-ingress.enc.yaml', 'ml-superset-ingress.enc.yaml']:
            text = (ROOT / 'apps/secrets' / name).read_text()
            self.assertIn('ENC[AES256_GCM,', text)
            self.assertIn('sops:', text)
        airflow = json.loads((ROOT / 'apps/ml/airflow.json').read_text())['spec']['template']['spec']['containers'][0]
        env = {e['name']: e for e in airflow['env']}
        self.assertEqual(env['AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS']['value'], 'false')
        self.assertIn('secretKeyRef', env['AIRFLOW__API__BASE_URL']['valueFrom'])
        self.assertIn('secretKeyRef', env['AIRFLOW__CORE__EXECUTION_API_SERVER_URL']['valueFrom'])

    def test_superset_uses_secure_cookies_and_prefixed_health(self):
        text = (ROOT / 'apps/ml/superset_public_config.py').read_text()
        self.assertIn('SESSION_COOKIE_SECURE = True', text)
        self.assertIn('SESSION_COOKIE_PATH = os.environ["SUPERSET_APP_ROOT"]', text)
        spec = json.loads((ROOT / 'apps/ml/superset.json').read_text())['spec']['template']['spec']
        for probe in ['readinessProbe', 'startupProbe', 'livenessProbe']:
            self.assertIn('SUPERSET_APP_ROOT', spec['containers'][0][probe]['exec']['command'][-1])

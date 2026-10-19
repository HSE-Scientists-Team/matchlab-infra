"""Contracts of the opt-in server pilot; no cluster access."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ServerTests(unittest.TestCase):
    def test_server_is_opt_in_and_interfaces_are_private(self):
        release = (ROOT / 'clusters/homelab/ml-release.yaml').read_text()
        self.assertIn('suspend: true', release)
        self.assertNotIn('ml-release.yaml', (ROOT / 'clusters/homelab/kustomization.yaml').read_text())
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
        self.assertIn('kube_job_status_failed', (ROOT / 'apps/monitoring/config/alerts.yml').read_text())

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

"""Validate generated dashboards without requiring a live cluster."""
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name('generate-dashboards.py')
spec = importlib.util.spec_from_file_location('dashboards', MODULE)
dashboards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboards)

class DashboardContracts(unittest.TestCase):
    def test_stable_uids_datasource_and_queries(self):
        generated = dashboards.generate()
        self.assertEqual(len(generated), 4)
        self.assertEqual(len({d['uid'] for d in generated.values()}), 4)
        for dashboard in generated.values():
            self.assertFalse(dashboard['editable'])
            self.assertEqual(len({p['id'] for p in dashboard['panels']}), len(dashboard['panels']))
            for panel in dashboard['panels']:
                self.assertEqual(panel['datasource']['uid'], 'matchlab-prometheus')
                self.assertTrue(panel['targets'][0]['expr'])

    def test_regeneration_is_clean(self):
        import subprocess
        subprocess.run(['python3', str(MODULE), '--check'], check=True)

    def test_manual_dashboards_use_persistent_database(self):
        root = MODULE.parents[1]
        provider = (root / 'apps/monitoring/config/dashboards.yml').read_text()
        self.assertIn('allowUiUpdates: false', provider)
        self.assertIn('folder: MatchLab GitOps', provider)
        self.assertIn('/var/lib/grafana', (root / 'apps/monitoring/grafana.yaml').read_text())

if __name__ == '__main__':
    unittest.main()

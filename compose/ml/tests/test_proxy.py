"""Proxy trust is enabled only behind the isolated Traefik ingress."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]

class AirflowProxyContract(unittest.TestCase):
    def test_plugin_uses_official_root_extension_and_keeps_ui_isolated(self):
        source = (ROOT / 'apps/ml/airflow_proxy_plugin.py').read_text()
        tree = ast.parse(source)
        declaration = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'fastapi_root_middlewares' for t in n.targets))
        config = declaration.value.elts[0]
        values = {k.value: v for k, v in zip(config.keys, config.values)}
        self.assertEqual(values['middleware'].id, 'ProxyHeadersMiddleware')
        self.assertEqual(ast.literal_eval(values['kwargs']), {'trusted_hosts': '*'})
        policy = json.loads((ROOT / 'apps/ml/ui-network-policy.json').read_text())['spec']
        self.assertIn('airflow', policy['podSelector']['matchExpressions'][0]['values'])
        for rule in policy['ingress']:
            for peer in rule['from']:
                self.assertEqual(peer['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'], 'kube-system')
                self.assertEqual(peer['podSelector']['matchLabels']['app.kubernetes.io/name'], 'traefik')
        deployment = json.loads((ROOT / 'apps/ml/airflow.json').read_text())['spec']['template']['spec']
        self.assertTrue(any(v['mountPath'] == '/opt/airflow/plugins' and v['readOnly'] for v in deployment['containers'][0]['volumeMounts']))
        self.assertTrue(any(v.get('configMap', {}).get('name') == 'airflow-proxy-plugin' for v in deployment['volumes']))

if __name__ == '__main__':
    unittest.main()

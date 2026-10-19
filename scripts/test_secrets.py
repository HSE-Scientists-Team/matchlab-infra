"""SOPS metadata must survive Kustomize flattening until Flux decryption."""
import subprocess
import unittest

class EncryptedSecretResources(unittest.TestCase):
    def test_sops_metadata_survives_kustomize(self):
        result = subprocess.check_output(['kubectl', 'kustomize', 'apps/secrets'], text=True)
        documents = result.split('\n---\n')
        secrets = [doc for doc in documents if 'kind: Secret\n' in doc]
        self.assertGreaterEqual(len(secrets), 6)
        for document in secrets:
            self.assertIn('sops:', document)
            self.assertIn('ENC[AES256_GCM,', document)

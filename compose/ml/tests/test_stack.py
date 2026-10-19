import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


STACK = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class StackTests(unittest.TestCase):
    def test_airflow_password_file_is_owned_at_runtime_and_not_in_task_environment(self):
        startup = module("start_airflow", STACK / "start_airflow.py")
        with tempfile.TemporaryDirectory() as root:
            password_file = Path(root) / "passwords.json"
            with patch.dict(os.environ, {"ML_AIRFLOW_ADMIN_PASSWORD": "private-local-password",
                                        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE": str(password_file)}), patch.object(startup.os, "execvp") as execute:
                startup.main()
                self.assertNotIn("ML_AIRFLOW_ADMIN_PASSWORD", os.environ)
                self.assertEqual(json.loads(password_file.read_text()), {"analyst": "private-local-password"})
                self.assertEqual(password_file.stat().st_mode & 0o777, 0o600)
                execute.assert_called_once_with("airflow", ["airflow", "standalone"])

    def test_initialization_is_private_unique_and_non_overwriting(self):
        launcher = module("stack", STACK / "stack.py")
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            backend = root / "backend"
            (backend / "ml").mkdir(parents=True)
            (backend / "ml" / "pyproject.toml").write_text("")
            local = root / "local"
            with patch.object(launcher, "LOCAL", local), patch.object(launcher, "ENV", local / ".env"), patch("sys.stdout", new_callable=io.StringIO) as output:
                launcher.initialize(backend)
                content = (local / ".env").read_text()
                self.assertEqual((local / ".env").stat().st_mode & 0o777, 0o600)
                self.assertEqual((local / "airflow-passwords.json").stat().st_mode & 0o777, 0o600)
                values = dict(line.split("=", 1) for line in content.splitlines())
                self.assertNotEqual(values["ML_SOURCE_PASSWORD"], values["ML_BI_PASSWORD"])
                self.assertNotIn(values["ML_BI_PASSWORD"].strip("'"), output.getvalue())
                with self.assertRaises(SystemExit):
                    launcher.initialize(backend)
                self.assertEqual(content, (local / ".env").read_text())

    def test_dashboard_definitions_and_layout(self):
        bootstrap = module("bootstrap", STACK / "superset" / "bootstrap.py")
        definitions = json.loads((STACK / "superset" / "dashboards.json").read_text())
        self.assertEqual(len(definitions), 4)
        charts = [chart for dashboard in definitions for chart in dashboard["charts"]]
        self.assertEqual(len(charts), 15)
        self.assertEqual(len({chart["key"] for chart in charts}), len(charts))
        views = {"overview", "project_status", "registrations", "user_segments", "universities", "skill_supply",
                 "project_types", "role_demand", "skill_demand", "recruitment", "team_formation", "recommendation_quality"}
        self.assertEqual({chart["view"] for chart in charts}, views)
        from types import SimpleNamespace
        layout = bootstrap.layout([SimpleNamespace(id=i, uuid=str(i), slice_name=str(i)) for i in range(3)])
        self.assertEqual(layout["GRID_ID"]["children"], ["ROW-0", "ROW-2"])
        self.assertEqual(layout["CHART-2"]["meta"]["width"], 12)


if __name__ == "__main__":
    unittest.main()

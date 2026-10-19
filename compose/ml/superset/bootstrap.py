"""Idempotent local dashboards for the pinned Superset 6.1 ORM.

Only MatchLab-managed chart UUIDs/dashboard slugs are updated. No user dashboards
or databases are deleted. Definitions contain no credentials or personal rows.
"""

import json
import os
from pathlib import Path
import subprocess
from uuid import NAMESPACE_URL, uuid5


def layout(charts):
    positions = {"DASHBOARD_VERSION_KEY": "v2",
                 "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
                 "GRID_ID": {"id": "GRID_ID", "type": "GRID", "parents": ["ROOT_ID"], "children": []}}
    for offset in range(0, len(charts), 2):
        row_id = "ROW-" + str(offset)
        pair = charts[offset:offset+2]
        positions["GRID_ID"]["children"].append(row_id)
        positions[row_id] = {"id": row_id, "type": "ROW", "parents": ["ROOT_ID", "GRID_ID"],
                             "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for chart in pair:
            chart_id = "CHART-" + str(chart.id)
            positions[row_id]["children"].append(chart_id)
            positions[chart_id] = {"id": chart_id, "type": "CHART", "children": [],
                                  "parents": ["ROOT_ID", "GRID_ID", row_id],
                                  "meta": {"chartId": chart.id, "uuid": str(chart.uuid), "sliceName": chart.slice_name,
                                           "width": 12 // len(pair), "height": 50}}
    return positions


def main():
    subprocess.run(["superset", "db", "upgrade"], check=True)
    subprocess.run(["superset", "init"], check=True)
    from superset.app import create_app
    from superset import db, security_manager
    app = create_app()
    with app.app_context():
        # Model fields need the app's encryption factory initialized first.
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice
        from superset.connectors.sqla.models import SqlaTable

        admin = security_manager.find_user(username="analyst")
        if admin is None:
            admin = security_manager.add_user("analyst", "Local", "Analyst", "analyst@localhost.invalid",
                                              security_manager.find_role("Admin"), os.environ["SUPERSET_ADMIN_PASSWORD"])
            if not admin:
                raise RuntimeError("Could not create local Superset analyst")
        database = db.session.query(Database).filter_by(database_name="MatchLab analytics (read only)").one_or_none()
        if database is None:
            database = Database(database_name="MatchLab analytics (read only)")
            db.session.add(database)
        database.sqlalchemy_uri = os.environ["SUPERSET_ANALYTICS_URL"]
        database.expose_in_sqllab = False
        database.allow_dml = False
        database.allow_run_async = False
        db.session.flush()
        datasets = {}
        definitions = json.loads(Path(__file__).with_name("dashboards.json").read_text())
        for definition in definitions:
            charts = []
            for spec in definition["charts"]:
                view = spec["view"]
                if view not in datasets:
                    dataset = db.session.query(SqlaTable).filter_by(database_id=database.id, schema="analytics", table_name=view).one_or_none()
                    if dataset is None:
                        dataset = SqlaTable(database_id=database.id, schema="analytics", table_name=view, owners=[admin])
                        db.session.add(dataset)
                        db.session.flush()
                    dataset.fetch_metadata()
                    datasets[view] = dataset
                dataset = datasets[view]
                chart_uuid = uuid5(NAMESPACE_URL, "matchlab/dashboard/" + spec["key"])
                chart = db.session.query(Slice).filter_by(uuid=chart_uuid).one_or_none()
                if chart is None:
                    chart = Slice(uuid=chart_uuid, owners=[admin])
                    db.session.add(chart)
                chart.slice_name = spec["title"]
                chart.datasource_type, chart.datasource_id = "table", dataset.id
                chart.viz_type = "big_number_total" if "metric" in spec else "table"
                params = {"viz_type": chart.viz_type, "datasource": f"{dataset.id}__table",
                          "adhoc_filters": [], "time_range": "No filter", "row_limit": 1000}
                if "metric" in spec:
                    # Metrics are code-owned view columns, never raw SQL from users.
                    params["metric"] = {"expressionType": "SQL", "sqlExpression": 'MAX("' + spec["metric"] + '")',
                                        "label": spec["title"], "optionName": "metric_" + spec["key"]}
                    params.update(subheader="Latest completed snapshot", y_axis_format=",d")
                else:
                    params.update(query_mode="raw", all_columns=spec["columns"], order_by_cols=[],
                                  include_search=True, page_length=20, table_timestamp_format="smart_date")
                chart.params = json.dumps(params)
                db.session.flush()
                charts.append(chart)
            dashboard = db.session.query(Dashboard).filter_by(slug=definition["slug"]).one_or_none()
            if dashboard is None:
                dashboard = Dashboard(slug=definition["slug"], owners=[admin])
                db.session.add(dashboard)
            dashboard.dashboard_title = definition["title"]
            dashboard.description = definition["description"]
            dashboard.published = True
            dashboard.slices = charts
            dashboard.position_json = json.dumps(layout(charts))
            dashboard.json_metadata = json.dumps({"refresh_frequency": 360, "cross_filters_enabled": False})
        db.session.commit()
    subprocess.run(["superset", "init"], check=True)
    print("Provisioned four local MatchLab dashboards; analyst uses the generated private password.")


if __name__ == "__main__":
    main()

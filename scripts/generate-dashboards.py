#!/usr/bin/env python3
"""Generate versioned Grafana dashboards. No network or third-party packages required."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'apps/monitoring/dashboards'
DS = {'type': 'prometheus', 'uid': 'matchlab-prometheus'}

def variable(name, query):
    return {'name': name, 'label': name.capitalize(), 'type': 'query', 'datasource': DS,
            'query': query, 'refresh': 1, 'multi': True, 'includeAll': True,
            'allValue': '.*', 'current': {'text': 'All', 'value': '$__all'}}

def dashboard(key, title, variables, panels):
    result = {'uid': 'matchlab-' + key, 'title': title, 'schemaVersion': 39, 'version': 1,
              'editable': False, 'tags': ['matchlab', 'gitops', 'KAN-60'], 'timezone': 'browser',
              'time': {'from': 'now-1h', 'to': 'now'}, 'refresh': '30s',
              'templating': {'list': variables}, 'panels': []}
    for index, (title, expr, unit, legend, kind) in enumerate(panels):
        panel = {'id': index + 1, 'title': title, 'type': kind, 'datasource': DS,
                 'gridPos': {'h': 9, 'w': 12, 'x': (index % 2) * 12, 'y': (index // 2) * 9},
                 'targets': [{'refId': 'A', 'expr': expr, 'legendFormat': legend,
                              'instant': kind == 'table', 'format': 'table' if kind == 'table' else 'time_series'}],
                 'fieldConfig': {'defaults': {'unit': unit}, 'overrides': []},
                 'options': {'legend': {'displayMode': 'table', 'placement': 'bottom'},
                             'tooltip': {'mode': 'multi'}}}
        if kind == 'table':
            panel['options'] = {'showHeader': True}
            panel['transformations'] = [{'id': 'organize', 'options': {'excludeByName': {'Time': True, 'Value': True}}}]
        result['panels'].append(panel)
    return result

def ts(title, expr, unit='short', legend='{{service}}'):
    return title, expr, unit, legend, 'timeseries'
def table(title, expr):
    return title, expr, 'short', '', 'table'

def generate():
    svc = variable('service', 'label_values(up{job="matchlab-services"}, service)')
    container = variable('service', 'label_values(kube_pod_container_info{namespace="matchlab"}, container)')
    node = variable('node', 'label_values(node_uname_info, node)')
    sel = 'service=~"$service"'
    pods = 'namespace="matchlab",pod=~"($service)-.*",container!="",container!="POD"'
    error = 'result=~"5..|Unknown|Internal|Unavailable|DataLoss|DeadlineExceeded|ResourceExhausted"'
    app = dashboard('application', 'MatchLab — Application', [svc], [
        table('Running binary versions and commits', 'matchlab_build_info{' + sel + '}'),
        ts('Requests / second', 'sum by (service) (rate(matchlab_requests_total{' + sel + '}[$__rate_interval]))', 'reqps'),
        ts('Server errors / second', 'sum by (service) (rate(matchlab_requests_total{' + sel + ',' + error + '}[$__rate_interval]))', 'reqps'),
        ts('Request latency p95', 'histogram_quantile(0.95, sum by (service, le) (rate(matchlab_request_duration_seconds_bucket{' + sel + '}[$__rate_interval])))', 's'),
        ts('In-flight requests', 'sum by (service,protocol) (matchlab_requests_in_flight{' + sel + '})', 'short', '{{service}} {{protocol}}'),
        ts('HTTP results', 'sum by (route,result) (rate(matchlab_requests_total{' + sel + ',protocol="http"}[$__rate_interval]))', 'reqps', '{{route}} {{result}}'),
        ts('RPC operations and results', 'sum by (service,route,result) (rate(matchlab_requests_total{' + sel + ',protocol="grpc"}[$__rate_interval]))', 'reqps', '{{service}} {{route}} {{result}}'),
        ts('Operation count in selected time range', 'sum by (service,route) (increase(matchlab_requests_total{' + sel + '}[$__range]))', 'short', '{{service}} {{route}}'),
        ts('Go goroutines', 'go_goroutines{' + sel + '}'),
        ts('Go heap in use', 'go_memstats_heap_inuse_bytes{' + sel + '}', 'bytes'),
        ts('SQL connections in use', 'go_sql_in_use_connections{' + sel + '}'),
        ts('SQL connection waits / second', 'rate(go_sql_wait_count_total{' + sel + '}[$__rate_interval])'),
    ])
    services = dashboard('services', 'MatchLab — Services and releases', [container], [
        table('Running image, digest, pod and node identity', 'kube_pod_container_info{namespace="matchlab",container=~"$service"}'),
        ts('Container CPU cores', 'sum by (pod) (rate(container_cpu_usage_seconds_total{' + pods + '}[$__rate_interval]))', 'cores', '{{pod}}'),
        ts('Container RAM — working set', 'sum by (pod) (container_memory_working_set_bytes{' + pods + '})', 'bytes', '{{pod}}'),
        ts('Configured RAM limit', 'sum by (pod) (kube_pod_container_resource_limits{namespace="matchlab",container=~"$service",resource="memory"})', 'bytes', '{{pod}}'),
        ts('Restarts in selected time range', 'sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="matchlab",container=~"$service"}[$__range]))', 'short', '{{pod}}'),
        ts('CPU throttled periods', '100 * sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{' + pods + '}[$__rate_interval])) / clamp_min(sum by (pod) (rate(container_cpu_cfs_periods_total{' + pods + '}[$__rate_interval])), 0.001)', 'percent', '{{pod}}'),
        ts('Container writable filesystem (when exported by runtime)', 'sum by (pod) (container_fs_usage_bytes{' + pods + '})', 'bytes', '{{pod}}'),
        ts('Persistent volume used (when supported by CSI)', 'kubelet_volume_stats_used_bytes{namespace="matchlab"}', 'bytes', '{{persistentvolumeclaim}}'),
    ])
    nodes = dashboard('nodes', 'MatchLab — Virtual machines', [node], [
        ts('VM CPU busy', '100 * (1 - avg by (node) (rate(node_cpu_seconds_total{node=~"$node",mode="idle"}[$__rate_interval])))', 'percent', '{{node}}'),
        ts('VM RAM used', 'node_memory_MemTotal_bytes{node=~"$node"} - node_memory_MemAvailable_bytes{node=~"$node"}', 'bytes', '{{node}}'),
        ts('VM RAM available', 'node_memory_MemAvailable_bytes{node=~"$node"}', 'bytes', '{{node}}'),
        ts('VM root disk used', 'node_filesystem_size_bytes{node=~"$node",mountpoint="/",fstype!~"tmpfs|overlay"} - node_filesystem_avail_bytes{node=~"$node",mountpoint="/",fstype!~"tmpfs|overlay"}', 'bytes', '{{node}}'),
        ts('Metrics volume free', 'node_filesystem_avail_bytes{node=~"$node",mountpoint="/var/lib/matchlab-metrics"}', 'bytes', '{{node}}'),
        ts('VM root disk free', 'node_filesystem_avail_bytes{node=~"$node",mountpoint="/",fstype!~"tmpfs|overlay"}', 'bytes', '{{node}}'),
        ts('VM disk reads', 'rate(node_disk_read_bytes_total{node=~"$node",device!~"loop.*|ram.*"}[$__rate_interval])', 'Bps', '{{node}} {{device}}'),
        ts('VM disk writes', 'rate(node_disk_written_bytes_total{node=~"$node",device!~"loop.*|ram.*"}[$__rate_interval])', 'Bps', '{{node}} {{device}}'),
        ts('VM network receive', 'rate(node_network_receive_bytes_total{node=~"$node",device!~"lo|veth.*|cni.*|flannel.*"}[$__rate_interval])', 'Bps', '{{node}} {{device}}'),
        ts('VM network transmit', 'rate(node_network_transmit_bytes_total{node=~"$node",device!~"lo|veth.*|cni.*|flannel.*"}[$__rate_interval])', 'Bps', '{{node}} {{device}}'),
        ts('VM load average, 5 minutes', 'node_load5{node=~"$node"}', 'short', '{{node}}'),
    ])
    monitoring = dashboard('monitoring', 'MatchLab — Monitoring health', [], [
        ts('Scrape targets up', 'up', 'short', '{{job}} {{instance}}'),
        ts('Samples ingested / second', 'rate(prometheus_tsdb_head_samples_appended_total[$__rate_interval])'),
        ts('Active time series', 'prometheus_tsdb_head_series'),
        ts('TSDB blocks', 'prometheus_tsdb_storage_blocks_bytes', 'bytes'),
        ts('WAL and head chunks', 'prometheus_tsdb_wal_storage_size_bytes + prometheus_tsdb_head_chunks_storage_size_bytes', 'bytes'),
        ts('Total tracked TSDB bytes — budget 10 GiB', 'prometheus_tsdb_storage_blocks_bytes + prometheus_tsdb_wal_storage_size_bytes + prometheus_tsdb_head_chunks_storage_size_bytes', 'bytes'),
        table('Active alert rules (notifications not configured)', 'ALERTS{alertstate="firing"}'),
        ts('Series scraped per target', 'scrape_samples_post_metric_relabeling', 'short', '{{job}} {{instance}}'),
        ts('Prometheus RSS', 'process_resident_memory_bytes{job="prometheus"}', 'bytes'),
        ts('Targets exceeding scrape sample limit', 'rate(prometheus_target_scrapes_exceeded_sample_limit_total[$__rate_interval])'),
    ])
    return dict(application=app, services=services, nodes=nodes, monitoring=monitoring)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for name, value in generate().items():
        expected = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        target = ROOT / (name + '.json')
        if args.check:
            if target.read_text() != expected:
                raise SystemExit(f'{target.name} is out of date; run scripts/generate-dashboards.py')
        else:
            target.write_text(expected)

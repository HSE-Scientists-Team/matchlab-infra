"""Explicit local API acceptance test. Creates labelled local accounts/projects.

Run only after stack.py up, using the isolated matchlab-ml-local Compose project.
No server URL override exists. Tokens/passwords stay in memory and are not logged.
Created business records remain in the local volume for inspection. Stops only
recommendation-redis temporarily; Auth Redis is never stopped.
"""

import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

STACK = Path(__file__).resolve().parent
sys.path.insert(0, str(STACK))
from stack import compose

API = 'http://127.0.0.1:8080/api/v1'
MAIL = 'http://127.0.0.1:8025/api/v1'


def request(path, method='GET', data=None, token=None, expected=200, mail=False):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request((MAIL if mail else API) + path,
                  data=json.dumps(data).encode() if data is not None else None,
                  method=method, headers=headers)
    try:
        with urlopen(req, timeout=40) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        status, raw = error.code, error.read()
    if status != expected:
        # Never include credentials, headers, raw email or auth response bodies.
        raise AssertionError(f'{method} {path.split("?")[0]}: HTTP {status}, expected {expected}')
    return json.loads(raw) if raw else None


def account(label, run):
    email = f'ml-test-{run}-{label}@hse.ru'
    password = secrets.token_urlsafe(24)
    credentials = {'email': email, 'password': password}
    request('/auth/register', 'POST', credentials, expected=201)
    for _ in range(30):
        messages = request('/messages?limit=100', mail=True)['messages']
        matching = [m for m in messages if any(t.get('Address') == email for t in m.get('To', []))]
        if matching:
            message = request('/message/' + matching[0]['ID'], mail=True)
            token_match = re.search(r'[?&]token=([A-Za-z0-9_-]+)', message.get('Text', '') + message.get('HTML', ''))
            if token_match:
                request('/auth/email/confirm', 'POST', {'token': token_match[1]}, expected=204)
                break
        time.sleep(0.5)
    else:
        raise AssertionError('Local confirmation email not received')
    login = request('/auth/login', 'POST', credentials)
    profile = {'display_name': 'ML local test ' + label, 'skills': ['python', 'postgresql'],
               'interests': ['data', 'science'], 'about': 'Explicit local recommendation acceptance test',
               'specialization': 'Data science', 'open_to_collaboration': True,
               'project_types': ['scientific'], 'contact_email': 'private@localhost.invalid',
               'telegram': 'private-local-test'}
    request('/users/me/profile', 'PUT', profile, login['access_token'])
    return login['user_id'], login['access_token'], profile


def project(owner_token, title, slots=1):
    result = request('/projects', 'POST', {
        'title': title, 'type': 'scientific', 'field': 'Data science',
        'problem': 'Validate local recommendation filtering', 'goal': 'Test safe live hydration',
        'tags': ['data', 'python'], 'planned_start': '2026-10-18', 'planned_end': '2027-01-18',
        'roles': [{'title': 'Analyst', 'description': 'Local test vacancy', 'skills': ['python'], 'slots': slots}]},
        owner_token, expected=201)
    # Current Project.Create publishes directly into recruiting state.
    assert result['status'] == 'recruiting'
    return result



def recommendations(kind, token, excluded=(), required=(), cached=False):
    result = request('/recommendations/' + kind + '?limit=100', token=token)
    key = 'user_id' if kind == 'people' else 'id'
    ids = {item[key] for item in result['items']}
    assert not ids.intersection(excluded), f'{kind}: ineligible card was served'
    assert set(required).issubset(ids), f'{kind}: expected eligible local card missing'
    metadata = result['recommendation']
    assert {m['id'] for m in metadata['items']} == ids, 'metadata/card IDs differ'
    assert all('private@' not in json.dumps(item) and 'private-local-test' not in json.dumps(item)
               for item in result['items']), 'private contact leaked'
    if cached:
        assert metadata['run_id'] and metadata['model'] == 'baseline-v1', 'batch ranking was not served'
    return result


def main():
    run = secrets.token_hex(4)
    request('/recommendations/people', expected=401)
    viewer, viewer_token, _ = account('viewer', run)
    target, target_token, target_profile = account('target', run)
    owner, owner_token, _ = account('owner', run)
    _, filler_token, _ = account('filler', run)
    projects = [project(owner_token, f'ML local test {run} {name}', 2 if name == 'joined' else 1) for name in ['open', 'closed', 'full', 'joined']]
    assert compose(['run', '--rm', 'ml-batch']) == 0, 'batch failed'
    recommendations('people', viewer_token, excluded=[viewer], required=[target], cached=True)
    recommendations('projects', viewer_token, required=[p['id'] for p in projects], cached=True)
    assert request('/project-joins', token=owner_token)['items'] == [], 'recommendations created a join request'
    request('/users/me/blocks/' + owner, 'PUT', {}, viewer_token, expected=204)
    recommendations('projects', viewer_token, excluded=[p['id'] for p in projects])
    request('/users/me/blocks/' + owner, 'DELETE', token=viewer_token, expected=204)
    request('/users/me/blocks/' + viewer, 'PUT', {}, target_token, expected=204)
    recommendations('people', viewer_token, excluded=[viewer, target])
    request('/users/me/blocks/' + viewer, 'DELETE', token=target_token, expected=204)
    target_profile['open_to_collaboration'] = False
    request('/users/me/profile', 'PUT', target_profile, target_token)
    recommendations('people', viewer_token, excluded=[target])
    target_profile['open_to_collaboration'] = True
    request('/users/me/profile', 'PUT', target_profile, target_token)
    request('/projects/' + projects[1]['id'] + '/transitions', 'POST',
            {'action': 'unpublish', 'expected_revision': projects[1]['revision']}, owner_token)
    for p, token in [(projects[2], filler_token), (projects[3], viewer_token)]:
        application = request('/projects/' + p['id'] + '/applications', 'POST',
                              {'role_id': p['roles'][0]['id'], 'message': 'Explicit local test action'}, token, expected=201)
        request('/project-joins/' + application['id'] + '/decision', 'POST', {'accept': True}, owner_token)
    recommendations('projects', viewer_token, excluded=[p['id'] for p in projects[1:]], required=[projects[0]['id']])
    assert compose(['stop', 'recommendation-redis']) == 0
    try:
        for kind in ['people', 'projects']:
            result = recommendations(kind, viewer_token)
            assert result['recommendation']['model'] == 'fallback-v1'
            assert all(m['fallback'] for m in result['recommendation']['items'])
    finally:
        assert compose(['start', 'recommendation-redis']) == 0
    # Same token still works: stopping the recommendation cache did not invalidate Auth.
    recommendations('people', viewer_token, required=[target])
    print('PASS: real registration/email/login/profile/project APIs, cached ranking, private contacts, reverse block, closed profile, closed/full/joined projects, Redis outage fallback and session isolation.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

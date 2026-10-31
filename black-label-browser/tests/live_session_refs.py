"""Real-engine replay of session identity through the stdio MCP and the product executor.

Synthetic localhost login only, in a temporary state root. Sends nothing outside
this machine and uses no owner profile, credential or desktop input.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import executor
import session_refs

PASSWORD = 'SYNTHETIC-CANARY-' + secrets.token_hex(8)
SESSIONS = {}
SUBMISSIONS = []


class Provider(BaseHTTPRequestHandler):
    def _send(self, status, body='', headers=()):
        data = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _account(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            name, _, value = part.strip().partition('=')
            if name == 'sid' and value in SESSIONS:
                return SESSIONS[value]
        return None

    def do_GET(self):
        if self.path.startswith('/login'):
            self._send(200, '<!doctype html><title>Sign in</title><h1>Sign in</h1><form method="post" action="/login">'
                            '<label>Email<input name="email" type="email" autocomplete="username"></label>'
                            '<label>Password<input name="password" type="password" autocomplete="current-password"></label>'
                            '<button type="submit">Sign in</button></form>')
        elif self.path.startswith('/me'):
            account = self._account()
            if account:
                self._send(200, f'<!doctype html><title>Account</title><meta name="user-login" content="{account}"><h1>Signed in as {account}</h1>')
            else:
                self._send(302, headers=[('Location', '/login')])
        else:
            self._send(404, 'missing')

    def do_POST(self):
        fields = parse_qs(self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode())
        email, password = fields.get('email', [''])[0], fields.get('password', [''])[0]
        SUBMISSIONS.append(email)
        if password != PASSWORD:
            self._send(401, '<title>Sign in</title><h1>Wrong password</h1>')
            return
        token = secrets.token_hex(16)
        SESSIONS[token] = email
        # Only a persistent cookie: proves the login outlives the process, including a crash.
        self._send(302, headers=[('Location', '/me'), ('Set-Cookie', f'sid={token}; Max-Age=86400; Path=/; HttpOnly; SameSite=Lax')])

    def log_message(self, *args):
        pass


class Mcp:
    def __init__(self, env):
        self.sequence = 0
        self.process = subprocess.Popen([sys.executable, str(ROOT / 'server/server.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self.rpc('initialize', {'protocolVersion': '2025-06-18'})

    def rpc(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        assert select.select([self.process.stdout], [], [], 60)[0], 'MCP timeout'
        return json.loads(self.process.stdout.readline())

    def call(self, name, **args):
        result = self.rpc('tools/call', {'name': 'browser_' + name, 'arguments': args})['result']
        if result.get('isError'):
            raise RuntimeError(result['content'][0]['text'])
        return json.loads(result['content'][0]['text'])

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=20)


def by(snapshot, **wanted):
    for element in snapshot['elements']:
        if all(element.get(key) == value for key, value in wanted.items()):
            return element['id']
    raise AssertionError(f'no element {wanted}')


def login(run, base, email, browser='chrome'):
    run('open', browser=browser, url=base + '/login')
    page = run('snapshot', browser=browser)
    run('bound_fill', browser=browser, element=by(page, type='email'), text=email, kind='username', allowed_origins=[base])
    page = run('snapshot', browser=browser)
    run('bound_fill', browser=browser, element=by(page, type='password'), text=PASSWORD, kind='password', allowed_origins=[base])
    page = run('snapshot', browser=browser)
    run('click', browser=browser, element=by(page, tag='button'))
    time.sleep(0.4)


def identity(run, base, browser='chrome'):
    run('open', browser=browser, url=base + '/me')
    return run('page_meta', browser=browser, names=['user-login'])['meta']['user-login']


def expect_error(code, function):
    try:
        function()
    except (executor.ExecutorError, ValueError, RuntimeError) as exc:
        assert str(exc).startswith(code), f'expected {code}, got {exc}'
        return str(exc)
    raise AssertionError('expected ' + code)


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    results = {}
    with tempfile.TemporaryDirectory(prefix='bl-session-') as temp:
        root = Path(temp)
        env = {**os.environ, 'BL_BROWSER_STATE_ROOT': str(root), 'BL_BROWSER_PRODUCT': 'utah'}
        for name in ('BL_BROWSER_SESSION', 'BL_BROWSER_PROFILE', 'BL_BROWSER_SESSION_REF', 'CODEX_THREAD_ID'):
            env.pop(name, None)
        options = dict(state_root=root, product='utah')
        founder = session_refs.create_session('fixture', 'founder@example.test', role='founder', env=env)['reference']
        company = session_refs.create_session('fixture', 'company@example.test', role='company', env=env)['reference']

        # ACCT-001 and graceful restart: login, process exit, exact reopen, same remote identity.
        first = executor.SessionExecutor(founder, **options)
        status = first.open()
        assert status['session_reference'] == founder and status['lease_generation'] == 1
        login(first.call, base, 'founder@example.test')
        assert identity(first.call, base) == 'founder@example.test'
        first.close()
        second = executor.SessionExecutor(founder, **options)
        status = second.open()
        assert status['session_reference'] == founder and status['lease_generation'] == 2
        assert identity(second.call, base) == 'founder@example.test', 'login lost across graceful restart'
        results['reopen_after_exit'] = {'reference_unchanged': True, 'remote_identity': 'founder@example.test', 'lease_generations': [1, 2]}

        # ACCT-002: busy returns the lease; no second writer, no new store.
        stores = sorted(path.name for path in (root / 'accounts').iterdir() if path.name != 'index')
        third = executor.SessionExecutor(founder, **options)
        message = expect_error('ISOLATED_PROFILE_BUSY', third.open)
        results['busy'] = json.loads(message[message.index('{'):])
        assert results['busy']['generation'] == 2
        assert stores == sorted(path.name for path in (root / 'accounts').iterdir() if path.name != 'index')

        # ACCT-004: kill the worker just after a login; reopen keeps the identity and leases fence.
        second.close()
        crash = executor.SessionExecutor(company, **options)
        crash.open()
        login(crash.call, base, 'company@example.test')
        assert identity(crash.call, base) == 'company@example.test'
        os.kill(crash._process.pid, signal.SIGKILL)  # This test's own worker only.
        crash._process.wait(timeout=10)
        expect_error('ISOLATED_BROWSER_CLOSED', lambda: crash.call('snapshot', browser='chrome'))
        assert crash.reconcile_required
        crash.close()
        time.sleep(1.5)
        after = executor.SessionExecutor(company, **options)
        status = after.open()
        survived = identity(after.call, base)
        assert survived == 'company@example.test', 'crash lost the login'
        results['crash'] = {'remote_identity': survived, 'lease_generation': status['lease_generation']}
        after.close()

        # ACCT-012: founder and company stay separate after both restarts.
        with executor.SessionExecutor(founder, **options) as check:
            assert identity(check.call, base) == 'founder@example.test'
        with executor.SessionExecutor(company, **options) as check:
            assert identity(check.call, base) == 'company@example.test'
        results['founder_company_separate'] = True

        # Missing and cross-product: typed refusal, nothing created.
        ghost = 'acct_' + 'b' * 24
        expect_error('SESSION_NOT_FOUND', executor.SessionExecutor(ghost, **options).open)
        assert not (root / 'accounts' / ('b' * 24)).exists()
        expect_error('SESSION_SCOPE_DENIED', executor.SessionExecutor(founder, state_root=root, product='ace').open)
        results['missing_and_scope'] = 'typed refusal; no store created'

        # Credential binding: wrong origin, wrong field and a cross-origin page all refused, value never sent.
        with executor.SessionExecutor(founder, **options) as check:
            check.call('open', browser='chrome', url=base + '/login')
            page = check.call('snapshot', browser='chrome')
            expect_error('CREDENTIAL_ORIGIN_MISMATCH', lambda: check.call('bound_fill', browser='chrome', element=by(page, type='password'), text=PASSWORD, kind='password', allowed_origins=['https://example.test']))
            page = check.call('snapshot', browser='chrome')
            expect_error('CREDENTIAL_FIELD_MISMATCH', lambda: check.call('bound_fill', browser='chrome', element=by(page, type='email'), text=PASSWORD, kind='password', allowed_origins=[base]))
            page = check.call('snapshot', browser='chrome')
            assert page['elements'] and all(element.get('value') != PASSWORD for element in page['elements'])
            assert PASSWORD not in json.dumps(page)
        results['credential_binding'] = 'wrong origin and wrong field refused; canary absent from the snapshot'

        # Model-facing MCP: exact reopen works, the recorded double hash fails, broker commands are absent.
        mcp_env = {**env, 'BL_BROWSER_PRODUCT': 'utah'}
        client = Mcp(mcp_env)
        assert client.call('session', action='reopen', reference=founder)['reopened'] is True
        status = client.call('status')
        assert status['session_reference'] == founder
        client.call('open', browser='chrome', url=base + '/me')
        snapshot = client.call('snapshot', browser='chrome')
        assert 'Signed in as founder@example.test' in snapshot['text']
        expect_error('ISOLATED_PROFILE_BUSY', executor.SessionExecutor(founder, **options).open)
        expect_error('SESSION_NOT_FOUND', lambda: client.call('session', action='reopen', reference=ghost))
        assert client.call('session', action='current')['session_reference'] == founder, 'failed reopen changed the binding'
        listed = {row['account'] for row in client.call('session', action='list')['sessions']}
        assert listed == {'founder@example.test', 'company@example.test'}
        names = {tool['name'] for tool in client.rpc('tools/list', {})['result']['tools']}
        assert 'browser_session' in names and not {'browser_bound_fill', 'browser_page_meta'} & names
        client.close()
        digest = founder.removeprefix('acct_')
        blocked = Mcp({**mcp_env, 'BL_BROWSER_SESSION': digest})
        expect_error('SESSION_REFERENCE_PASSED_AS_NAME', lambda: blocked.call('status'))
        blocked.close()
        assert not (root / 'sessions').exists() or not any((root / 'sessions').iterdir())
        results['mcp'] = {'exact_reopen': True, 'double_hash_refused': True, 'broker_tools_hidden': True}

        # Secret scan of everything the run left on disk except the engine's own cookie/profile stores.
        leaked = []
        for path in root.rglob('*'):
            if path.is_file() and path.suffix in ('.json', '.lock', '.log', '.txt') and path.stat().st_size < 4_000_000:
                if PASSWORD.encode() in path.read_bytes():
                    leaked.append(path.name)
        assert not leaked, leaked
        results['canary_in_records'] = 0
    server.shutdown()
    results['synthetic_submissions'] = len(SUBMISSIONS)
    print(json.dumps({'pass': True, 'results': results}, indent=2))


if __name__ == '__main__':
    main()

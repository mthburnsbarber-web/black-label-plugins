"""Product-owned connection to the isolated worker for one exact session reference.

Products built on this engine use this over private pipes. It adds the broker-only commands
(bound_fill, page_meta) that the model-facing MCP tools never expose. Secrets
travel only over the worker's stdin; engine stderr is discarded because engine
call logs can contain submitted values.
"""
import json
import os
from pathlib import Path
import select
import subprocess

try:
    from . import session_refs  # Vendored inside a product package.
except ImportError:
    import session_refs

WORKER = Path(__file__).resolve().parent / 'headless.mjs'
READ_ONLY = {'snapshot', 'status', 'screenshot', 'auth', 'receipt', 'find', 'capture', 'page_meta', 'settle'}


class ExecutorError(RuntimeError):
    """A typed, secret-free failure. .code is the leading error token."""

    def __init__(self, message):
        super().__init__(message)
        self.code = str(message).split(':', 1)[0]


def default_runtime():
    path = Path.home() / '.blacklabel/isolated-browser/runtime.json'
    if not path.is_file():
        raise ExecutorError('ISOLATED_BROWSER_NOT_INSTALLED: no runtime is configured')
    return json.loads(path.read_text())


class SessionExecutor:
    def __init__(self, reference, *, state_root, product, node=None, playwright=None, timeout=45, connection=None, worker=None, owner_visible=False):
        if node is None or playwright is None:
            runtime = default_runtime()
            node, playwright = node or runtime['node'], playwright or runtime['playwright']
        self.env = {**os.environ, 'BL_BROWSER_STATE_ROOT': str(state_root), 'BL_BROWSER_PRODUCT': product,
                    'BL_BROWSER_PLAYWRIGHT': str(playwright)}
        for name in ('BL_BROWSER_SESSION', 'BL_BROWSER_PROFILE', 'BL_BROWSER_PROFILE_ID', 'BL_BROWSER_SESSION_REF', 'BL_BROWSER_ACCOUNT_REF', 'BL_BROWSER_HANDOFF'):
            self.env.pop(name, None)
        if owner_visible:
            self.env['BL_BROWSER_HANDOFF'] = '1'  # Only an owner-run handoff passes this; the worker then refuses input.
        self.node, self.timeout = str(node), timeout
        self.worker = str(worker or WORKER)
        self.reference, self.connection = reference, connection
        self.binding = None
        self.lease = None
        self._lock = None
        self._process = None
        self._pending = False
        self.reconcile_required = False

    def open(self):
        """Reopen the exact store, take its lease and handshake the protocol. Missing stays missing."""
        try:
            self.binding = session_refs.resolve(self.reference, self.env)
            self._lock, self.lease = session_refs.acquire(self.binding, self.env, self.connection, wait_seconds=session_refs.LEASE_WAIT_SECONDS)
        except ValueError as exc:
            raise ExecutorError(str(exc)) from None
        env = {**self.env, **session_refs.worker_environment(self.binding, self.lease)}
        try:
            self._process = subprocess.Popen([self.node, self.worker], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env, pass_fds=(self._lock.fileno(),))
        except OSError:
            self._release()
            raise ExecutorError('ISOLATED_ENGINE_UNAVAILABLE: the worker could not start') from None
        status = self.call('status')
        if status.get('protocol_version') != session_refs.PROTOCOL:
            self.close()
            raise ExecutorError('PROTOCOL_MISMATCH: worker speaks ' + str(status.get('protocol_version')) + ', this client needs ' + session_refs.PROTOCOL)
        if status.get('session_reference') != self.reference:
            self.close()
            raise ExecutorError('SESSION_IDENTITY_MISMATCH: the worker opened a different store than requested')
        return status

    def call(self, command, **args):
        if self._process is None or self._process.poll() is not None:
            self.reconcile_required = True
            raise ExecutorError('ISOLATED_BROWSER_CLOSED: outcome unknown; reopen and inspect before repeating any action')
        if self._pending:
            if not select.select([self._process.stdout], [], [], 0)[0]:
                raise ExecutorError('ISOLATED_ACTION_PENDING: previous operation is still finishing; do not repeat it')
            self._process.stdout.readline()
            self._pending = False
        if self.reconcile_required and command not in READ_ONLY:
            raise ExecutorError('ISOLATED_RECONCILIATION_REQUIRED: read a fresh snapshot before another mutation')
        try:
            self._process.stdin.write(json.dumps({'command': command, **args}) + '\n')
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            self.reconcile_required = True
            raise ExecutorError('ISOLATED_BROWSER_CLOSED: outcome unknown; reopen and inspect before repeating any action') from None
        if not select.select([self._process.stdout], [], [], self.timeout)[0]:
            self._pending = True
            self.reconcile_required = True
            raise ExecutorError('ISOLATED_BROWSER_TIMEOUT: outcome unknown; reconcile before repeating any action')
        line = self._process.stdout.readline()
        if not line:
            self.reconcile_required = True
            raise ExecutorError('ISOLATED_BROWSER_CLOSED: outcome unknown; reopen and inspect before repeating any action')
        try:
            response = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            self.reconcile_required = True
            raise ExecutorError('ISOLATED_BROWSER_PROTOCOL_ERROR: inspect a fresh snapshot before another action') from None
        if not response.get('ok'):
            error = response.get('error', 'ISOLATED_ACTION_FAILED')
            if error.startswith(('ISOLATED_ACTION_TIMEOUT', 'ISOLATED_ACTION_FAILED', 'ISOLATED_FORM_PARTIAL', 'ISOLATED_EXECUTION_STATE_WRITE_FAILED')):
                self.reconcile_required = True
            raise ExecutorError(error)
        if command == 'snapshot':
            self.reconcile_required = False
        if command == 'click_verify' and response['result'].get('receipt', {}).get('state') in ('started', 'unconfirmed'):
            self.reconcile_required = True
        return response['result']

    def _release(self):
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def close(self):
        process, self._process = self._process, None
        if process is not None:
            try:
                process.stdin.close()
                process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                return  # Keep the lease until the worker really exits; never signal it.
        self._release()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

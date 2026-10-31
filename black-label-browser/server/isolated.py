"""Private headless browser transport. Never falls back to desktop input."""
import atexit
import fcntl
import re
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import threading

import session_refs

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / '.blacklabel/isolated-browser/runtime.json'
_process = None
_lock = threading.Lock()
_pending = False
_profile_lock = None
_reconcile_required = False
_binding = None
_lease = None


def runtime():
    if not RUNTIME.is_file():
        raise ValueError('ISOLATED_BROWSER_NOT_INSTALLED: run this plugin install.py; desktop fallback is disabled')
    value = json.loads(RUNTIME.read_text())
    for key in ('node', 'playwright'):
        if not Path(value[key]).exists():
            raise ValueError('ISOLATED_BROWSER_RUNTIME_MISSING: rerun install.py; desktop fallback is disabled')
    return value


def close():
    global _process, _profile_lock
    if _process is not None:
        try:
            _process.stdin.close()
            _process.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            return  # Never signal a shared-host descendant.
        _process = None
    if _profile_lock is not None:
        _profile_lock.close()
        _profile_lock = None


atexit.register(close)


def acquire_profile(identity, named=False):
    """Kernel lock lives as long as this connection/worker, with no stale PID lock."""
    if named and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity):
        raise ValueError('INVALID_PROFILE: use 1-80 letters, digits, underscores or hyphens')
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    key = ('profile-' if named else 'session-') + digest
    directory = session_refs.state_root() / 'locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / (key + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handle = os.fdopen(descriptor, 'a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError('ISOLATED_PROFILE_BUSY: this private profile is in use; close its connection before reconnecting')
    return handle, digest


def session(args):
    """Create, reopen or inspect a durable session. Reopen selects the exact store only."""
    global _binding, _lease, _profile_lock, _process
    action = args.get('action')
    env = os.environ.copy()
    with _lock:
        if action == 'list':
            return {'sessions': session_refs.list_sessions(env), 'protocol_version': session_refs.PROTOCOL}
        if action == 'create':
            return session_refs.create_session(args.get('provider'), args.get('account'),
                                               workspace=args.get('workspace', 'default'), role=args.get('role'), env=env)
        if action == 'current':
            binding = _binding or session_refs.from_environment(env, os.getpid())
            return {'session_reference': binding['reference'], 'kind': binding['kind'], 'running': _process is not None and _process.poll() is None,
                    'lease_generation': _lease['generation'] if _lease else None, 'protocol_version': session_refs.PROTOCOL,
                    'next': 'A reference selects the store, not a signed-in state. Verify the remote account before writing.'}
        if action not in ('reopen', 'named'):
            raise ValueError('INVALID_SESSION_ACTION: expected current, list, create, reopen or named')
        if _pending or _reconcile_required:
            raise ValueError('ISOLATED_RECONCILIATION_REQUIRED: read a fresh snapshot of the current session before switching')
        target = session_refs.resolve(args.get('reference'), env) if action == 'reopen' else session_refs.named(args.get('name'))
        if _binding and _binding['reference'] == target['reference'] and _profile_lock is not None:
            return {'session_reference': target['reference'], 'kind': target['kind'], 'lease_generation': _lease['generation'],
                    'reopened': False, 'next': 'Already bound. Verify the remote account before writing.'}
        # Take the target lease first: a busy or missing target leaves this connection unchanged.
        handle, lease = session_refs.acquire(target, env, 'mcp-' + str(os.getpid()), wait_seconds=session_refs.LEASE_WAIT_SECONDS)
        if _process is not None:
            try:
                _process.stdin.close()
                _process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                handle.close()
                raise ValueError('ISOLATED_SHUTDOWN_PENDING: the current session has not exited; nothing changed')
            _process = None
        if _profile_lock is not None:
            _profile_lock.close()
        _profile_lock, _binding, _lease = handle, target, lease
        return {'session_reference': target['reference'], 'kind': target['kind'], 'lease_generation': lease['generation'],
                'reopened': True, 'next': 'Exact store selected. Verify the remote account before writing.'}


def call(command, args):
    global _process, _pending, _reconcile_required, _profile_lock, _binding, _lease
    with _lock:
        if _pending:
            if not select.select([_process.stdout], [], [], 0)[0]:
                raise ValueError('ISOLATED_ACTION_PENDING: previous operation is still finishing; do not repeat it')
            _process.stdout.readline()  # Drain exactly the previous response, never misattribute it.
            _pending = False
        read_only = command in ('snapshot', 'status', 'screenshot', 'auth', 'receipt', 'find', 'capture', 'settle') or command in ('tabs', 'checkpoint') and args.get('action', 'list') == 'list'
        if _reconcile_required and not read_only:
            raise ValueError('ISOLATED_RECONCILIATION_REQUIRED: read a fresh snapshot before another mutation')
        if _process is None or _process.poll() is not None:
            config = runtime()
            env = os.environ.copy()
            env['BL_BROWSER_PLAYWRIGHT'] = config['playwright']
            binding = _binding or session_refs.from_environment(env, os.getpid())
            # A dead worker's lease is re-taken; a lease session() just took is kept.
            if _process is not None or _profile_lock is None or _lease is None or _lease['reference'] != binding['reference']:
                if _profile_lock is not None:
                    _profile_lock.close()
                    _profile_lock = None
                _profile_lock, _lease = session_refs.acquire(binding, env, 'mcp-' + str(os.getpid()), wait_seconds=session_refs.LEASE_WAIT_SECONDS)
            _binding = binding
            for name in ('BL_BROWSER_PROFILE_ID', 'BL_BROWSER_ACCOUNT_REF', 'BL_BROWSER_HANDOFF'):
                env.pop(name, None)
            env.update(session_refs.worker_environment(binding, _lease))
            try:
                _process = subprocess.Popen(
                    [config['node'], str(ROOT / 'server/headless.mjs')],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1, env=env, pass_fds=(_profile_lock.fileno(),))
            except Exception:
                _profile_lock.close()
                _profile_lock = None
                raise
        try:
            _process.stdin.write(json.dumps({'command': command, **args}) + '\n')
            _process.stdin.flush()
        except (BrokenPipeError, OSError):
            _reconcile_required = True
            raise ValueError('ISOLATED_BROWSER_CLOSED: outcome unknown; inspect a new snapshot before another action')
        if not select.select([_process.stdout], [], [], 45)[0]:
            # A mutation may still be finishing. Do not retry or launch a second worker.
            _pending = True
            _reconcile_required = True
            raise ValueError('ISOLATED_BROWSER_TIMEOUT: outcome unknown; reconcile the page before repeating any action')
        line = _process.stdout.readline()
        if not line:
            _reconcile_required = True
            raise ValueError('ISOLATED_BROWSER_CLOSED: inspect a new snapshot before repeating any action')
        try:
            response = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            _reconcile_required = True
            raise ValueError('ISOLATED_BROWSER_PROTOCOL_ERROR: inspect a new snapshot before another action')
        if not response.get('ok'):
            error = response.get('error', 'Isolated browser operation failed')
            if error.startswith(('ISOLATED_ACTION_TIMEOUT', 'ISOLATED_ACTION_FAILED', 'ISOLATED_FORM_PARTIAL', 'ISOLATED_EXECUTION_STATE_WRITE_FAILED')):
                _reconcile_required = True
            raise ValueError(error)
        if command == 'snapshot':
            _reconcile_required = False
        if command == 'click_verify' and response['result'].get('receipt', {}).get('state') in ('started', 'unconfirmed'):
            _reconcile_required = True
        return response['result']

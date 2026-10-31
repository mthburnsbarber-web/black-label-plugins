"""Exact account session references for the isolated executor.

create_session derives one identity and registers it. resolve reopens that exact
reference and never hashes it again, so a returned reference cannot select a
second store. A missing reference is an error, never an empty replacement.
These records hold no secrets and no model-supplied filesystem paths.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time

PROTOCOL = 'bl-account-exec/1'
_REFERENCE = re.compile(r'(acct_|session:|profile:)([a-f0-9]{24})')
_DIGEST = re.compile(r'[a-f0-9]{24}')
_NAME = re.compile(r'[a-zA-Z0-9_-]{1,80}')
_LABEL = re.compile(r'[^\x00-\x1f\x7f/\\]{1,200}')


def state_root(env=os.environ):
    configured = env.get('BL_BROWSER_STATE_ROOT')
    if not configured:
        return Path.home() / '.blacklabel/isolated-browser'
    root = Path(configured)
    if not root.is_absolute():
        raise ValueError('INVALID_STATE_ROOT: expected an absolute product-owned directory')
    return root


def product(env=os.environ):
    value = env.get('BL_BROWSER_PRODUCT') or 'agent'
    if not _NAME.fullmatch(value):
        raise ValueError('INVALID_PRODUCT: use 1-80 letters, digits, underscores or hyphens')
    return value


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _label(field, value):
    if not isinstance(value, str) or not _LABEL.fullmatch(value) or value != value.strip():
        raise ValueError('INVALID_ACCOUNT_BINDING: ' + field + ' must be a short plain label without path separators')
    return value


def _write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_record(path):
    try:
        if path.is_symlink() or path.stat().st_size > 64_000:
            raise ValueError('SESSION_RECORD_INVALID: expected a bounded private record')
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        raise ValueError('SESSION_RECORD_INVALID: the session record could not be read; it was left in place')


def create_session(provider, account, *, workspace='default', role=None, env=os.environ, replace_missing=False):
    """Register one store for one product/workspace/provider/account. Repeating it returns that store.

    replace_missing is an explicit owner decision after SESSION_NOT_FOUND. It never replaces a store that exists.
    """
    binding = {'product': product(env), 'workspace': _label('workspace', workspace),
               'provider': _label('provider', provider), 'account': _label('account', account)}
    if role is not None:
        _label('role', role)
    root = state_root(env) / 'accounts'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    key = hashlib.sha256(json.dumps([binding[k] for k in ('product', 'workspace', 'provider', 'account')]).encode()).hexdigest()
    index = root / 'index' / (key + '.json')
    with (root / '.registry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = _read_record(index)
        if existing:
            record = _read_record(root / existing['id'] / 'reference.json')
            if record is not None:
                return {**_public(record), 'created': False}
            if not replace_missing:
                # Never hand back a fresh blank store under an account that used to have one.
                raise ValueError('SESSION_NOT_FOUND: ' + 'acct_' + existing['id'] + ' is registered but its store is missing')
        identifier = secrets.token_hex(12)
        directory = root / identifier
        directory.mkdir(mode=0o700)
        record = {'version': 1, 'id': identifier, 'reference': 'acct_' + identifier, **binding,
                  'role': role, 'created_at': _now()}
        _write_private(directory / 'reference.json', record)
        _write_private(index, {'id': identifier})
    return {**_public(record), 'created': True}


def _public(record):
    return {key: record.get(key) for key in ('reference', 'product', 'workspace', 'provider', 'account', 'role', 'created_at')}


def resolve(reference, env=os.environ):
    """Return the exact registered store. Guessed values, paths and other products are refused."""
    match = _REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    if not match:
        raise ValueError('INVALID_SESSION_REFERENCE: use a reference returned by this executor; paths and names are refused')
    root, identifier = state_root(env), match.group(2)
    if match.group(1) == 'acct_':
        record = _read_record(root / 'accounts' / identifier / 'reference.json')
        if record is None:
            raise ValueError('SESSION_NOT_FOUND: ' + reference + ' is not registered here; nothing was created')
        if record.get('product') != product(env):
            raise ValueError('SESSION_SCOPE_DENIED: ' + reference + ' belongs to another product')
        return {'kind': 'account', 'id': identifier, 'reference': reference, 'lock': 'account-' + identifier}
    kind = 'session' if match.group(1) == 'session:' else 'profile'
    if not (root / (kind + 's') / identifier).is_dir():
        raise ValueError('SESSION_NOT_FOUND: ' + reference + ' has no store here; nothing was created')
    return {'kind': kind, 'id': identifier, 'reference': reference, 'lock': kind + '-' + identifier}


def named(name):
    """The separate explicit operation for a logical profile name. Hashes the name once."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError('INVALID_PROFILE: use 1-80 letters, digits, underscores or hyphens')
    digest = hashlib.sha256(name.encode()).hexdigest()[:24]
    return {'kind': 'profile', 'id': digest, 'reference': 'profile:' + digest, 'lock': 'profile-' + digest}


def logical(identity):
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return {'kind': 'session', 'id': digest, 'reference': 'session:' + digest, 'lock': 'session-' + digest}


def from_environment(env, pid):
    """Choose this connection's store. A returned digest is never hashed into a new one."""
    reference = env.get('BL_BROWSER_SESSION_REF')
    if reference:
        return resolve(reference, env)
    if env.get('BL_BROWSER_PROFILE') is not None:
        return named(env['BL_BROWSER_PROFILE'])
    name = env.get('BL_BROWSER_SESSION')
    if name and _DIGEST.fullmatch(name):
        raise ValueError('SESSION_REFERENCE_PASSED_AS_NAME: ' + name + ' is a returned digest; reopen it with session:' + name)
    return logical(name or env.get('CODEX_THREAD_ID') or 'mcp-' + str(pid))


#: A worker can still be closing its engine when the next connection opens, longer under load.
#: Waiting this long for that is not stealing: the kernel lock is only ever taken once it is free.
LEASE_WAIT_SECONDS = 12.0


def acquire(binding, env=os.environ, connection=None, wait_seconds=0.0):
    """Kernel lock plus a readable, monotonically increasing lease. Busy never steals or copies."""
    directory = state_root(env) / 'locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / (binding['lock'] + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handle = os.fdopen(descriptor, 'a+')
    lease_path = directory / (binding['lock'] + '.lease.json')
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() < deadline:
                time.sleep(0.25)
                continue
        handle.close()
        try:
            holder = _read_record(lease_path) or {}
        except ValueError:
            holder = {}
        raise ValueError('ISOLATED_PROFILE_BUSY: this private profile is in use; close its connection before reconnecting. '
                         + json.dumps({'reference': binding['reference'], 'holder_pid': holder.get('pid'),
                                       'generation': holder.get('generation'), 'since': holder.get('since')}))
    try:
        previous = _read_record(lease_path) or {}
    except ValueError:
        previous = {}
    generation = int(previous.get('generation') or 0) + 1
    lease = {'reference': binding['reference'], 'pid': os.getpid(), 'generation': generation,
             'since': _now(), 'connection': connection}
    _write_private(lease_path, lease)
    return handle, lease


def worker_environment(binding, lease):
    variables = {'BL_BROWSER_SESSION': binding['id'], 'BL_BROWSER_REFERENCE': binding['reference'],
                 'BL_BROWSER_LEASE_GENERATION': str(lease['generation'])}
    if binding['kind'] == 'profile':
        variables['BL_BROWSER_PROFILE_ID'] = binding['id']
    if binding['kind'] == 'account':
        variables['BL_BROWSER_ACCOUNT_REF'] = binding['id']
    return variables


def list_sessions(env=os.environ):
    root = state_root(env) / 'accounts'
    rows = []
    for path in sorted(root.glob('*/reference.json')) if root.is_dir() else []:
        record = _read_record(path)
        if record and record.get('product') == product(env):
            rows.append(_public(record))
    return rows

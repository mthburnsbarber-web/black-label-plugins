#!/usr/bin/env python3
"""Owner-run: show one exact hidden session in a visible window so a person can finish a provider's check.

Only a person starts this. It is not an MCP tool and never a fallback. The window is the same
store and the worker refuses all input while it is open. It stays up until the person closes it,
because a sign-in page or a check is what they came to finish. The task that was waiting then
reopens this same reference.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import executor
import session_refs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', help='a reference from browser_status or browser_session')
    parser.add_argument('--url', required=True, help='the page that was showing the check')
    parser.add_argument('--browser', default='chrome', choices=['chrome', 'safari'])
    parser.add_argument('--timeout', type=int, default=900, help='seconds to keep the window open')
    args = parser.parse_args()
    env = os.environ
    connection = executor.SessionExecutor(args.reference, state_root=session_refs.state_root(env), product=session_refs.product(env),
                                          connection='owner-handoff', owner_visible=True)
    try:
        connection.open()
        connection.call('open', browser=args.browser, url=args.url)
        print('Sign in or finish the check in the window, then close it. This session and its task are unchanged.', flush=True)
        deadline = time.monotonic() + args.timeout
        result = {'kind': 'unknown'}
        try:
            while time.monotonic() < deadline:
                result = connection.call('settle', browser=args.browser, budget_ms=5000)
                time.sleep(2)
        except executor.ExecutorError as exc:
            result = {**result, 'window': exc.code}  # The person closed it, most likely. Reopening decides.
        print(json.dumps({'session_reference': args.reference, 'page_state': result['kind'], 'url': result.get('url'),
                          'next': 'Reopen this reference and verify the account before writing.'}, indent=2))
        return 0
    except executor.ExecutorError as exc:
        print(json.dumps({'session_reference': args.reference, 'code': exc.code, 'detail': str(exc)}, indent=2))
        return 3
    finally:
        connection.close()


if __name__ == '__main__':
    sys.exit(main())

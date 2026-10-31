"""Replay independent chat input against each installed MCP entry point."""
import argparse
import json
from pathlib import Path
from http.server import ThreadingHTTPServer
import threading
import uuid

from live_isolated import Client, Fixture


def visible(snapshot, text):
    return any(text in str(e.get('value', '')) or text in str(e.get('title', ''))
               for e in snapshot['elements'])


def field(snapshot, title):
    return next(e['id'] for e in snapshot['elements'] if e.get('title') == title)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--entrypoint', action='append', required=True)
    options = parser.parse_args()
    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:' + str(fixture.server_port) + '/'
    report = {'fixture': url, 'entrypoints': [], 'scope': 'fresh independent chat connections'}
    try:
        for entrypoint in options.entrypoint:
            clients = [Client('chat-proof-' + uuid.uuid4().hex, Path(entrypoint)) for _ in range(2)]
            row = {'entrypoint': entrypoint, 'engines': []}
            try:
                statuses = [c.call('status') for c in clients]
                assert len({s['session'] for s in statuses}) == 2, 'Chat profiles collided'
                for status in statuses:
                    assert status['mode'] == 'isolated-headless'
                    assert status['owner_cursor_protected']
                    assert not any(status[k] for k in ('physical_pointer_input',
                        'desktop_keyboard_input', 'desktop_screen_capture', 'desktop_activation',
                        'owner_debugging_toggle_required', 'extension_required'))
                row['sessions'] = [s['session'] for s in statuses]
                for browser in ('chrome', 'safari'):
                    values = ['Chat A ' + uuid.uuid4().hex, 'Chat B ' + uuid.uuid4().hex]
                    for client in clients:
                        client.call('open', browser=browser, url=url)
                    for client, value in zip(clients, values):
                        snapshot = client.call('snapshot', browser=browser)
                        client.call('fill', browser=browser,
                                    element=field(snapshot, 'Unicode entry'), text=value)
                        snapshot = client.call('snapshot', browser=browser)
                        client.call('click', browser=browser,
                                    element=field(snapshot, 'Save fixture'))
                    snapshots = [c.call('snapshot', browser=browser) for c in clients]
                    for index, snapshot in enumerate(snapshots):
                        assert visible(snapshot, 'Saved: [' + values[index] + ']')
                        assert not visible(snapshot, values[1 - index]), 'Cross-chat input leaked'
                        assert snapshot['headless']
                    row['engines'].append({'browser': browser,
                        'separate_profiles': True, 'both_saves_read_back': True,
                        'cross_chat_input_leak': False, 'desktop_input': False})
                report['entrypoints'].append(row)
            finally:
                for client in clients:
                    client.close()
    finally:
        fixture.shutdown()
        fixture.server_close()
    Path(options.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed_entrypoints': len(report['entrypoints']),
        'passed_engine_pairs': sum(len(r['engines']) for r in report['entrypoints'])}))


if __name__ == '__main__':
    main()

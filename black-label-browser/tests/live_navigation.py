"""Exercise real headless Chromium through public MCP; localhost fixtures only."""
import argparse
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid
from urllib.parse import urlsplit

from live_workflow import Client


class Fixture(BaseHTTPRequestHandler):
    attempts = {}

    def do_GET(self):
        route = urlsplit(self.path).path
        type(self).attempts[route] = type(self).attempts.get(route, 0) + 1
        status, headers = 200, {}
        if route == '/delayed':
            body = '''<div aria-busy="true">Loading...</div><script>
            setTimeout(()=>{document.querySelector('div').outerHTML='<h1>Ready to use</h1><input aria-label="Actual name">';},450);
            </script>'''
        elif route == '/challenge':
            status, headers = 403, {'cf-mitigated':'challenge','Set-Cookie':'private_fixture_secret=not_for_diagnostics; HttpOnly'}
            body = '<h1>Opaque verification</h1>'
        elif route == '/soft-challenge':
            body = '<h1>Performing security verification</h1>'
        elif route == '/forbidden':
            status, body = 403, '<h1>Access denied</h1>'
        elif route == '/rate':
            status, headers, body = 429, {'Retry-After':'3600'}, '<h1>Wait before retrying</h1>'
        elif route == '/date-limit':
            status, headers, body = 503, {'Retry-After':format_datetime(datetime.now(timezone.utc)+timedelta(hours=1),usegmt=True)}, '<h1>Service unavailable</h1>'
        elif route == '/redirect':
            self.send_response(302);self.send_header('Location','/normal');self.end_headers();return
        elif route == '/network':
            self.connection.close();return
        else:
            body = '<h1>Normal article</h1><p>Article about captcha integrations</p>'
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        for key,value in headers.items():self.send_header(key,value)
        self.end_headers();self.wfile.write(('<!doctype html><title>Navigation fixture</title>'+body).encode())

    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=fixture.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(fixture.server_port)
    client=Client(args.entrypoint,'navigation-test-'+uuid.uuid4().hex)
    checks=[]
    try:
        status=client.call('status')
        assert status['mode']=='isolated-headless' and status['navigation_diagnostics'] and status['retry_after_guard']
        client.call('open',browser='chrome',url=base+'/delayed')
        page=client.call('snapshot',browser='chrome')
        assert 'Ready to use' in page['text'] and page['readiness']['ready_for_snapshot'],page
        assert any(row.get('title')=='Actual name' for row in page['elements']),page
        checks.append('first snapshot waits for delayed rendered controls')
        for route,kind in [('/normal','none_detected'),('/redirect','none_detected'),('/challenge','challenge'),('/soft-challenge','challenge'),('/forbidden','access_denied')]:
            client.call('open',browser='chrome',url=base+route+'?secret=omit-from-diagnostics#fragment')
            page=client.call('snapshot',browser='chrome')
            assert page['access']['kind']==kind,(route,page['access'])
            assert 'private_fixture_secret' not in json.dumps(page['access'])
            assert '?' not in page['access']['document']['url']
            if kind=='challenge':assert 'human_verification' in page['auth']['requirements']
            checks.append(route+': '+kind)
        client.call('open',browser='chrome',url=base+'/network',error='ISOLATED_ACTION_FAILED')
        page=client.call('snapshot',browser='chrome')
        assert page['access']['kind']=='navigation_error',page['access']
        checks.append('network failure remains distinct from provider challenge')
        client.call('open',browser='chrome',url=base+'/rate')
        page=client.call('snapshot',browser='chrome')
        assert page['access']['kind']=='rate_limited' and page['access']['document']['retry_at']
        for operation,options in [('open',{'url':base+'/rate'}),('tabs',{'action':'open','url':base+'/normal'}),('key',{'key':'ctrl+r'})]:
            client.call(operation,browser='chrome',error='ISOLATED_RETRY_LATER',**options)
        assert Fixture.attempts['/rate']==1,Fixture.attempts
        checks.append('Retry-After blocks repeated open, reload and new-tab requests without sending them')
        # Different origin remains usable during an origin-specific cooldown.
        alternate=base.replace('127.0.0.1','localhost')
        client.call('open',browser='chrome',url=alternate+'/date-limit')
        page=client.call('snapshot',browser='chrome')
        assert page['access']['kind']=='http_error' and page['access']['document']['retry_at']
        client.call('open',browser='chrome',url=alternate+'/normal',error='ISOLATED_RETRY_LATER')
        checks.append('HTTP-date Retry-After enforced; unrelated origin unaffected')
        for tab in client.call('tabs',browser='chrome')['tabs']:
            client.call('tabs',browser='chrome',action='close',tab=tab['id'])
        assert client.call('tabs',browser='chrome')['tabs']==[]
        args.output.write_text(json.dumps({'passed':True,'entrypoint':str(args.entrypoint.resolve()),'checks':checks,'final_tabs':0},indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':len(checks),'output':str(args.output)}))
    finally:
        client.close();fixture.shutdown()


if __name__=='__main__':main()

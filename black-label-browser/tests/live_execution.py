"""Real public-MCP execution and performance probes against localhost only."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import uuid

from live_workflow import Client


class Fixture(BaseHTTPRequestHandler):
    submissions = 0

    def do_GET(self):
        route = self.path.split('?')[0]
        if route == '/dense':
            body = '<output>Unchanged</output>' + ''.join(
                f'<button id="button-{i}" onclick="document.querySelector(\'output\').textContent=\'Clicked {i}\'">Item {i}</button>' for i in range(500))
        elif route == '/form':
            body = '''<input id="first" aria-label="First" oninput="document.getElementById('later').outerHTML=document.getElementById('later').outerHTML">
            <input id="later" aria-label="Later"><output>Ready</output>
            <button onclick="fetch('/submit',{method:'POST'}).then(r=>r.text()).then(t=>document.querySelector('output').textContent=t)">Submit once</button>
            <button onclick="fetch('/submit',{method:'POST'})">Submit with no confirmation</button>'''
        elif route == '/ambiguous':
            body = '''<input id="first" aria-label="First" oninput="let x=document.getElementById('later'); x.outerHTML=x.outerHTML+x.outerHTML">
            <input id="later" aria-label="Later">'''
        elif route == '/rate':
            self.send_response(429);self.send_header('Retry-After','3600');self.end_headers();self.wfile.write(b'<h1>Rate limit</h1>');return
        else:
            body = '<h1>Other origin works</h1>'
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
        self.wfile.write(('<!doctype html><title>Execution fixture</title>'+body).encode())

    def do_POST(self):
        assert self.path == '/submit'
        type(self).submissions += 1
        self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers()
        self.wfile.write(('Received submission '+str(type(self).submissions)).encode())

    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--benchmark-only',action='store_true')
    args=parser.parse_args()
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=fixture.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(fixture.server_port)
    profile='execution-test-'+uuid.uuid4().hex
    client=Client(args.entrypoint,'execution-'+uuid.uuid4().hex,profile)
    result={'entrypoint':str(args.entrypoint.resolve()),'checks':[]}
    field=lambda page,label:next(e for e in page['elements'] if e.get('title')==label and e.get('tag') in ('input','button'))
    try:
        client.call('open',browser='chrome',url=base+'/dense')
        samples=[]
        for _ in range(3):
            start=time.monotonic();page=client.call('snapshot',browser='chrome');samples.append(round((time.monotonic()-start)*1000,1))
            assert len([e for e in page['elements'] if e.get('tag')=='button'])==500
        client.call('click',browser='chrome',element=field(page,'Item 499')['id'])
        assert 'Clicked 499' in client.call('snapshot',browser='chrome')['text']
        result['snapshot_500_controls_ms']=samples
        result['checks'].append('500-control snapshots preserve target identity')
        if not args.benchmark_only:
            client.call('open',browser='chrome',url=base+'/form');page=client.call('snapshot',browser='chrome')
            filled=client.call('form',browser='chrome',fields=[{'element':field(page,'First')['id'],'action':'fill','text':'One'},
                {'element':field(page,'Later')['id'],'action':'fill','text':'Two'}])
            assert filled['fields_confirmed']==2 and filled['targets_rebound']==1,filled
            page=client.call('snapshot',browser='chrome');assert field(page,'Later')['value']=='Two'
            result['checks'].append('uniquely identified rerendered field recovered without duplicate input')
            submitted=client.call('click_verify',browser='chrome',element=field(page,'Submit once')['id'],receipt_id='submit-one',
                expect={'condition':'text','text':'Received submission 1'},timeout_ms=3000)
            assert submitted['receipt']['state']=='verified' and Fixture.submissions==1,submitted
            client.close();client=Client(args.entrypoint,'resumed-'+uuid.uuid4().hex,profile)
            receipt=client.call('receipt',browser='chrome',receipt_id='submit-one')
            assert receipt['receipt']['state']=='verified' and receipt['verification_current'] is False
            replay=client.call('click_verify',browser='chrome',element='expired-id',receipt_id='submit-one',
                expect={'condition':'text','text':'Received submission 1'},timeout_ms=3000)
            assert replay['already_recorded'] and not replay['action_attempted'] and Fixture.submissions==1,replay
            result['checks'].append('verified receipt survives reconnect and prevents a second server submission')
            client.call('open',browser='chrome',url=base+'/form');page=client.call('snapshot',browser='chrome')
            unknown=client.call('click_verify',browser='chrome',element=field(page,'Submit with no confirmation')['id'],receipt_id='uncertain-one',
                expect={'condition':'text','text':'Never appears'},timeout_ms=150)
            assert unknown['receipt']['state']=='unconfirmed' and Fixture.submissions==2,unknown
            client.close();client=Client(args.entrypoint,'resumed-again-'+uuid.uuid4().hex,profile)
            replay=client.call('click_verify',browser='chrome',element='expired-id',receipt_id='uncertain-one',
                expect={'condition':'text','text':'Never appears'},timeout_ms=150)
            assert not replay['action_attempted'] and Fixture.submissions==2,replay
            result['checks'].append('unconfirmed submission is not retried after reconnect')
            client.call('open',browser='chrome',url=base+'/form',error='RECONCILIATION_REQUIRED')
            assert client.call('receipt',browser='chrome',receipt_id='uncertain-one')['receipt']['state']=='unconfirmed'
            client.call('snapshot',browser='chrome')
            client.call('open',browser='chrome',url=base+'/form');page=client.call('snapshot',browser='chrome')
            client.call('click_verify',browser='chrome',element=field(page,'Submit once')['id'],receipt_id='existing-outcome',
                expect={'condition':'text','text':'Ready'},error='EXPECTATION_ALREADY_PRESENT')
            assert Fixture.submissions==2
            result['checks'].append('already present text cannot falsely confirm a new action')
            client.call('open',browser='chrome',url=base+'/ambiguous');page=client.call('snapshot',browser='chrome')
            client.call('form',browser='chrome',fields=[{'element':field(page,'First')['id'],'action':'fill','text':'One'},
                {'element':field(page,'Later')['id'],'action':'fill','text':'must not apply'}],error='FORM_PARTIAL')
            page=client.call('snapshot',browser='chrome');assert all(e['value']=='' for e in page['elements'] if e.get('title')=='Later')
            result['checks'].append('ambiguous replacement rejected without typing into either candidate')
            client.call('open',browser='chrome',url=base+'/rate');client.call('snapshot',browser='chrome')
            client.close();client=Client(args.entrypoint,'cooldown-'+uuid.uuid4().hex,profile)
            client.call('open',browser='chrome',url=base+'/form',error='RETRY_LATER')
            client.call('open',browser='chrome',url=base.replace('127.0.0.1','localhost')+'/normal')
            result['checks'].append('provider cooldown survives reconnect; unrelated origin still works')
        for tab in client.call('tabs',browser='chrome')['tabs']:
            client.call('tabs',browser='chrome',action='close',tab=tab['id'])
        result['final_tabs']=len(client.call('tabs',browser='chrome')['tabs'])
        assert result['final_tabs']==0
        result['passed']=True
        args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    finally:
        client.close();fixture.shutdown()


if __name__=='__main__':main()

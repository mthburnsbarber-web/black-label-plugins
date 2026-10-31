"""Real-engine regression for associated labels in styled third-party forms."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid
from live_workflow import Client

HTML = '''<!doctype html><title>Styled controls fixture</title>
<style>.offscreen {position:absolute;left:-140000px} label {display:block;padding:12px}</style>
<input class="offscreen" type="checkbox" id="terms" onchange="document.querySelector('output').textContent='Changes: '+(++window.changes)">
<label for="terms">Associated terms</label>
<input class="offscreen" type="radio" id="radio" name="option"><label for="radio">Associated radio</label>
<input class="offscreen" type="checkbox" id="disabled" disabled><label for="disabled">Disabled terms</label>
<input class="offscreen" type="checkbox" id="blocked"><label for="blocked" onclick="event.preventDefault()">Blocked terms</label>
<input aria-label="Untouched" value="original"><output>Changes: 0</output><script>window.changes=0</script>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self,*args): pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    client=Client(args.entrypoint,'styled-'+uuid.uuid4().hex)
    report={'entrypoint':str(args.entrypoint.resolve()),'engines':[]}
    try:
        for browser in ['chrome','safari']:
            client.call('open',browser=browser,url=f'http://127.0.0.1:{server.server_port}/')
            def snap(): return client.call('snapshot',browser=browser)
            def field(page,name): return next(e for e in page['elements'] if e.get('tag')=='input' and e.get('title')==name)
            def check(name,value):
                page=snap()
                return client.call('form',browser=browser,fields=[{'element':field(page,name)['id'],'action':'check','checked':value}])
            assert check('Associated terms',True)['associated_labels_used']==1
            assert field(snap(),'Associated terms')['checked']
            assert check('Associated terms',True)['associated_labels_used']==0
            assert 'Changes: 1' in snap()['text']
            assert check('Associated terms',False)['associated_labels_used']==1
            assert not field(snap(),'Associated terms')['checked']
            assert 'Changes: 2' in snap()['text']
            assert check('Associated radio',True)['associated_labels_used']==1
            page=snap()
            client.call('form',browser=browser,error='INVALID_FORM',fields=[
                {'element':field(page,'Untouched')['id'],'action':'fill','text':'must not apply'},
                {'element':field(page,'Disabled terms')['id'],'action':'check','checked':True}])
            assert field(snap(),'Untouched')['value']=='original'
            page=snap()
            client.call('form',browser=browser,error='ISOLATED_FORM_PARTIAL',fields=[
                {'element':field(page,'Blocked terms')['id'],'action':'check','checked':True},
                {'element':field(page,'Untouched')['id'],'action':'fill','text':'must not apply'}])
            page=snap()
            assert not field(page,'Blocked terms')['checked']
            assert field(page,'Untouched')['value']=='original'
            for tab in client.call('tabs',browser=browser)['tabs']:
                client.call('tabs',browser=browser,action='close',tab=tab['id'])
            report['engines'].append({'browser':browser,'passed':True,
                'checks':['offscreen input uses its exact associated label','repeat is idempotent',
                          'check and uncheck readback','radio selection','disabled prevalidation preserves earlier fields',
                          'prevented label action stops before later field mutation']})
        report.update(passed=True,final_tabs=0)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
    finally:
        client.close();server.shutdown()


if __name__=='__main__': main()

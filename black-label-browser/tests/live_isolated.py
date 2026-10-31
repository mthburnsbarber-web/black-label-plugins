"""Focused real-engine acceptance through the installed stdio MCP; no desktop input."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
HTML='''<!doctype html><meta charset="utf-8"><title>Isolated browser acceptance</title>
<style>body{font:18px sans-serif;padding:24px}button,input,select{margin:8px}#bottom{margin-top:1800px}</style>
<h1>Isolated browser acceptance</h1>
<label>Unicode entry<input aria-label="Unicode entry" id="entry" oninput="events.textContent='Input event: '+this.value"></label>
<output id="events">No input events</output><br>
<label>Password<input type="password" name="password" aria-label="Password"></label><br>
<button id="save" onclick="result.textContent='Saved: ['+entry.value+']';localStorage.setItem('acceptance','persisted')">Save fixture</button>
<output id="result">No save</output><br>
<label>Virtual checkbox<input id="check" aria-label="Virtual checkbox" type="checkbox"></label>
<label>Choice<select aria-label="Choice" onchange="choice.textContent='Choice: '+this.value"><option>First</option><option>Second</option></select></label>
<output id="choice">No choice</output><br>
<label>Fixture upload<input type="file" aria-label="Fixture upload" onchange="upload.textContent='Uploaded: '+this.files[0].name"></label>
<output id="upload">No file</output><br>
<button onclick="dialogResult.textContent=confirm('Fixture confirmation')?'Accepted':'Dismissed'">Open fixture dialog</button><output id="dialogResult">No dialog</output>
<a href="/popup" target="_blank">Open agent page</a>
<a href="/download" download>Download fixture</a>
<iframe title="Fixture frame" srcdoc="<button onclick=&quot;document.querySelector('output').textContent='Frame clicked'&quot;>Frame button</button><output>No frame click</output>"></iframe>
<p id="persisted"></p><p id="scroll">Scroll: 0</p>
<p id="bottom">Bottom of private viewport</p>
<script>persisted.textContent='Storage: '+localStorage.getItem('acceptance');addEventListener('scroll',()=>document.getElementById('scroll').textContent='Scroll: '+Math.round(scrollY));</script>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/download':
            data=b'Private browser download proof\n';self.send_response(200)
            self.send_header('Content-Disposition','attachment; filename="browser-proof.txt"')
            self.send_header('Content-Type','application/octet-stream')
        else:
            data=(HTML if self.path!='/popup' else '<title>Private popup</title><h1>Private popup loaded</h1>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass


class Client:
    def __init__(self,session,entrypoint):
        self.sequence=0
        self.process=subprocess.Popen([sys.executable,str(entrypoint)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL,text=True,bufsize=1,env={**os.environ,'BL_BROWSER_SESSION':session})
        self.rpc('initialize',{'protocolVersion':'2025-06-18'})
    def rpc(self,method,params):
        self.sequence+=1
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.sequence,'method':method,'params':params})+'\n');self.process.stdin.flush()
        if not select.select([self.process.stdout],[],[],50)[0]:raise RuntimeError('MCP response timeout')
        response=json.loads(self.process.stdout.readline())
        assert response.get('id')==self.sequence, 'Response identity mismatch'
        return response['result']
    def call(self,name,expect_error=False,**args):
        result=self.rpc('tools/call',{'name':'browser_'+name,'arguments':args})
        if expect_error:
            assert result.get('isError'), 'Expected rejection';return result
        if result.get('isError'):raise RuntimeError(result['content'][0]['text'])
        if result['content'][0]['type']=='image':return result['content'][0]
        return json.loads(result['content'][0]['text'])
    def close(self):
        self.process.stdin.close();self.process.wait(timeout=20)
        assert self.process.returncode==0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--entrypoint',default=str(ROOT/'server/server.py'))
    options=parser.parse_args()
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=fixture.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(fixture.server_port)+'/'
    session='acceptance-'+uuid.uuid4().hex
    report={'fixture':url,'session':session,'entrypoint':options.entrypoint,'engines':[]}
    client=Client(session,Path(options.entrypoint))
    try:
        report['status']=client.call('status')
        assert report['status']['mode']=='isolated-headless'
        with tempfile.TemporaryDirectory(prefix='bl-hidden-test-') as directory:
            upload=Path(directory)/'fixture-proof.txt';upload.write_text('Local upload proof')
            for browser in ['chrome','safari']:
                checks=[]
                def call(name,**args):return client.call(name,browser=browser,**args)
                def snap():return call('snapshot')
                def find(snapshot,label,role=None):
                    return next(e for e in snapshot['elements'] if e.get('title')==label and (role is None or e.get('role')==role))
                def visible(snapshot,text):return any(text in str(e.get('value','')) or text in str(e.get('title','')) for e in snapshot['elements'])
                call('open',url=url)
                s=snap();assert s['headless'] and s['title']=='Isolated browser acceptance';checks.append('navigation')
                field=find(s,'Unicode entry','AXTextField');value='café — 日本語 ✓ '+browser
                call('fill',element=field['id'],text=value)
                stale=client.call('fill',browser=browser,element=field['id'],text='must reject',expect_error=True)
                assert 'STALE_ELEMENT' in stale['content'][0]['text'];checks.append('stale ID rejection')
                s=snap();assert visible(s,'Input event: '+value);checks.append('Unicode input events')
                call('type',element=find(s,'Unicode entry','AXTextField')['id'],text=' appended')
                s=snap();assert visible(s,'Input event: '+value+' appended');checks.append('focused Unicode typing')
                call('click',element=find(s,'Save fixture','AXButton')['id'])
                s=snap();assert visible(s,'Saved: ['+value+' appended]');checks.append('form save readback')
                call('fill',element=find(s,'Unicode entry','AXTextField')['id'],text='')
                s=snap();assert find(s,'Unicode entry','AXTextField')['value']=='';checks.append('empty fill')
                clipboard=client.call('key',browser=browser,key='cmd+v',expect_error=True)
                assert 'UNSUPPORTED_KEY' in clipboard['content'][0]['text'];checks.append('system clipboard protected')
                s=snap()
                call('fill',element=find(s,'Password','AXTextField')['id'],text='synthetic-secret-442211')
                s=snap();assert 'synthetic-secret-442211' not in json.dumps(s);checks.append('secure-field redaction')
                call('fill',element=find(s,'Choice','AXPopUpButton')['id'],text='Second')
                s=snap();assert visible(s,'Choice: Second');checks.append('select choice')
                checkbox=find(s,'Virtual checkbox','AXCheckBox');x,y,w,h=checkbox['frame']
                image=call('screenshot');data=base64.b64decode(image['data']);assert data.startswith(b'\x89PNG\r\n\x1a\n');checks.append('engine screenshot')
                call('click_at',x=x+w/2,y=y+h/2)
                s=snap();assert find(s,'Virtual checkbox','AXCheckBox')['checked'];checks.append('virtual mouse click')
                call('click',element=find(s,'Fixture upload','AXTextField')['id'])
                call('choose_file',path=str(upload))
                s=snap();assert visible(s,'Uploaded: fixture-proof.txt');checks.append('file attachment')
                call('click',element=find(s,'Frame button','AXButton')['id'])
                s=snap();assert visible(s,'Frame clicked');checks.append('iframe input')
                call('click',element=find(s,'Open fixture dialog','AXButton')['id'])
                s=snap();assert any(e['role']=='AXDialog' for e in s['elements'])
                call('key',key='escape')
                s=snap();assert visible(s,'Dismissed');checks.append('dialog inspect and dismiss')
                call('click',element=find(s,'Open agent page','AXLink')['id'])
                for attempt in range(10):
                    s=snap()
                    if s.get('title')=='Private popup':break
                    time.sleep(.1)
                assert s['title']=='Private popup' and len(s['windows'])==2;checks.append('private popup')
                origin=next(e for e in s['windows'] if e['title']=='Isolated browser acceptance')
                call('focus_window',element=origin['id'])
                s=snap();assert s['title']=='Isolated browser acceptance';checks.append('internal page selection')
                call('click',element=find(s,'Download fixture','AXLink')['id'])
                for attempt in range(10):
                    s=snap()
                    if s['downloads']:break
                    time.sleep(.1)
                assert Path(s['downloads'][0]['path']).read_text()=='Private browser download proof\n';checks.append('download bytes')
                call('scroll',amount=750)
                s=snap();scroll=next(e for e in s['elements'] if str(e.get('value','')).startswith('Scroll: '))
                assert scroll['value']!='Scroll: 0';checks.append('virtual wheel scroll')
                client.call('open',browser=browser,url='file:///etc/passwd',expect_error=True);checks.append('non-HTTP rejection')
                report['engines'].append({'browser':browser,'checks':checks,'passed':True})
                print(json.dumps(report['engines'][-1]),flush=True)
        client.close();client=Client(session,Path(options.entrypoint))
        for browser in ['chrome','safari']:
            client.call('open',browser=browser,url=url)
            s=client.call('snapshot',browser=browser)
            assert any('Storage: persisted' in str(e.get('value','')) for e in s['elements'])
        report['profile_persistence_after_restart']=True
        report['passed']=True
    finally:
        client.close();fixture.shutdown()
    if options.output:Path(options.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'engines':len(report['engines']),'profile_persistence':True}),flush=True)


if __name__=='__main__':main()

"""Real MCP/engine regression checks; localhost fixture credentials only."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time
import uuid

HTML = '''<!doctype html><meta charset="utf-8"><title>Workflow fixture</title>
<style>input,select,button{display:block;margin:10px}</style>
<div>Plain rendered status</div><table><tr><td>Table cell status</td></tr></table>
<button aria-label="Hover target" onmouseenter="document.querySelector('output').textContent='Hovered'">Hover me</button>
<div role="region" aria-label="Scroll panel" style="overflow:auto;height:80px" onscroll="document.querySelector('output').textContent='Panel scrolled'"><div style="height:1200px">Panel content</div></div>
<select aria-label="Object options"><option value="same">Alpha</option><option value="same">Beta</option></select>
<input aria-label="Name" required minlength="3"><input aria-label="Email" type="email" required>
<input aria-label="Remember" type="checkbox"><select aria-label="Platforms" multiple>
<option value="mac">Mac</option><option value="web">Web</option><option value="bad" disabled>Disabled</option></select>
<input aria-label="Password" type="password"><input aria-label="Verification code" autocomplete="one-time-code">
<input aria-label="Token" name="token"><input aria-label="Locked" disabled>
<input aria-label="First" oninput="document.querySelector('[aria-label=Later]')?.remove()"><input aria-label="Later">
<button onclick="document.querySelector('output').textContent='Saved locally'">Save fixture</button>
<button onclick="setTimeout(()=>document.querySelector('output').textContent='Ready after delay',150)">Delayed result</button>
<button onclick="document.querySelector('[aria-label=Name]').style.display='none'">Hide name</button>
<button onclick="confirm('Per-tab dialog')">Open modal</button>
<details><summary>Hidden platforms</summary><input aria-label="Hidden checkbox" type="checkbox"></details>
<a href="/popup" target="_blank">Popup fixture</a><output>Initial state</output>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        if self.path == '/login':
            self.send_header('Set-Cookie', 'fixture_session=local-only; HttpOnly; SameSite=Lax; Path=/')
            body = '<h1>Fixture login complete</h1>'
        elif self.path == '/logout':
            self.send_header('Set-Cookie','fixture_session=; Max-Age=0; HttpOnly; Path=/')
            body='<h1>Logged out</h1>'
        elif self.path == '/account':
            body = '<h1>Signed in as fixture@example.test</h1>' if 'fixture_session=local-only' in self.headers.get('Cookie', '') else '<h1>Login required</h1>'
        else:
            body = HTML
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


class Client:
    def __init__(self, entrypoint, session, profile=None):
        env = {k:v for k,v in os.environ.items() if k not in ('BL_BROWSER_PROFILE','BL_BROWSER_PROFILE_ID')}
        env['BL_BROWSER_SESSION'] = session
        if profile is not None:
            env['BL_BROWSER_PROFILE'] = profile
        self.proc = subprocess.Popen([sys.executable,str(entrypoint)], env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        self.seq = 0
        self.rpc('initialize',{'protocolVersion':'2025-06-18'})

    def rpc(self, method, params):
        self.seq += 1
        self.proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.seq,'method':method,'params':params})+'\n')
        self.proc.stdin.flush()
        assert select.select([self.proc.stdout],[],[],50)[0], 'MCP timeout'
        response = json.loads(self.proc.stdout.readline())
        assert response['id'] == self.seq
        return response['result']

    def call(self, name, error=None, **args):
        result = self.rpc('tools/call',{'name':'browser_'+name,'arguments':args})
        if error:
            assert result.get('isError') and error in result['content'][0]['text'], result
            return result
        assert not result.get('isError'), result
        content = result['content'][0]
        return content if content['type']=='image' else json.loads(content['text'])

    def close(self):
        if self.proc.stdin.closed:
            return
        self.proc.stdin.close()
        self.proc.wait(timeout=20)
        self.proc.stdout.close()
        assert self.proc.returncode == 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py')
    parser.add_argument('--output',type=Path)
    options=parser.parse_args()
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=fixture.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(fixture.server_port)
    profile='workflow-'+uuid.uuid4().hex
    client=Client(options.entrypoint,'first-'+uuid.uuid4().hex,profile)
    report={'entrypoint':str(options.entrypoint),'engines':[]}
    try:
        status=client.call('status')
        assert status['named_profile'] and status['tabs_limit']==5 and not status['owner_profile_imported']
        competitor=Client(options.entrypoint,'competitor',profile)
        try:
            competitor.call('status',error='ISOLATED_PROFILE_BUSY')
        finally:
            competitor.close()
        invalid=Client(options.entrypoint,'invalid','../escape')
        try:
            invalid.call('status',error='INVALID_PROFILE')
        finally:
            invalid.close()
        report['profile_exclusivity_and_validation']=True
        for browser in ['chrome','safari']:
            checks=[]
            def call(name,**args):return client.call(name,browser=browser,**args)
            def snap():return call('snapshot')
            def field(s,label):return next(e for e in s['elements'] if e.get('title')==label and e.get('tag') in ['input','select','button','a','summary'])
            call('open',url=url)
            s=snap()
            assert 'Plain rendered status' in s['text'] and 'Table cell status' in s['text']
            assert field(s,'Name')['constraints']['minLength']==3
            assert field(s,'Name')['validation']['valueMissing']
            checks.append('rendered text, table cells and field constraints')
            call('hover',element=field(s,'Hover target')['id'])
            assert 'Hovered' in snap()['text']
            s=snap();rect=field(s,'Hover target')['frame']
            call('move',x=rect[0]+rect[2]/2,y=rect[1]+rect[3]/2)
            s=snap();panel=next(e for e in s['elements'] if e.get('title')=='Scroll panel')
            call('scroll',element=panel['id'],amount=300)
            assert 'Panel scrolled' in snap()['text']
            checks.append('virtual hover, move and nested-panel scrolling')
            s=snap();obj=field(s,'Object options')
            call('form',error='INVALID_FORM',fields=[{'element':obj['id'],'action':'select','values':['same']}])
            s=snap();obj=field(s,'Object options')
            call('form',fields=[{'element':obj['id'],'action':'select','labels':['Beta']}])
            s=snap();obj=field(s,'Object options')
            assert [o['label'] for o in obj['options'] if o['selected']]==['Beta']
            checks.append('ambiguous option values rejected; labels select exact option')
            assert not any(e.get('title')=='Hidden checkbox' for e in s['elements'])
            call('click',element=field(s,'Hidden platforms')['id'])
            s=snap()
            assert field(s,'Hidden checkbox')['checked'] is False
            checks.append('closed dropdown controls are excluded until opened')
            assert field(s,'Name')['invalid']
            fields=[{'element':field(s,'Name')['id'],'action':'fill','text':'Alpha & Beta'},
                {'element':field(s,'Email')['id'],'action':'fill','text':'fixture@example.test'},
                {'element':field(s,'Remember')['id'],'action':'check','checked':True},
                {'element':field(s,'Platforms')['id'],'action':'select','values':['mac','web']}]
            result=call('form',fields=fields)
            assert result['fields_confirmed']==4 and result['submitted'] is False
            s=snap()
            assert field(s,'Name')['value']=='Alpha & Beta' and not field(s,'Email')['invalid'] and field(s,'Remember')['checked']
            assert {o['value'] for o in field(s,'Platforms')['options'] if o['selected']}=={'mac','web'}
            checks.append('batch form readback and validity')
            call('form',fields=[{'element':field(s,'Remember')['id'],'action':'check','checked':True}])
            assert field(snap(),'Remember')['checked']
            checks.append('idempotent checkbox state')
            s=snap()
            call('form',error='INVALID_FORM',fields=[{'element':field(s,'Name')['id'],'action':'fill','text':'must not apply'},
                {'element':field(s,'Locked')['id'],'action':'fill','text':'blocked'}])
            assert field(snap(),'Name')['value']=='Alpha & Beta'
            checks.append('all-target prevalidation before mutation')
            s=snap()
            call('form',error='INVALID_FORM',fields=[{'element':field(s,'Platforms')['id'],'action':'select','values':['bad']}])
            checks.append('disabled option rejection')
            s=snap()
            call('form',error='ISOLATED_FORM_PARTIAL',fields=[{'element':field(s,'First')['id'],'action':'fill','text':'remove next'},
                {'element':field(s,'Later')['id'],'action':'fill','text':'missing'}])
            call('click',error='RECONCILIATION_REQUIRED',element=field(s,'Save fixture')['id'])
            s=snap()
            assert field(s,'First')['value']=='remove next'
            checks.append('dynamic partial failure requires reconciliation')
            secrets=['synthetic-password','654321','synthetic-token']
            call('form',fields=[{'element':field(s,label)['id'],'action':'fill','text':value}
                for label,value in zip(['Password','Verification code','Token'],secrets)])
            s=snap()
            assert all(value not in json.dumps(s) for value in secrets)
            image=call('screenshot')
            # Verify filled credential controls are covered by the mask pixels.
            from PIL import Image
            png=Image.open(BytesIO(base64.b64decode(image['data']))).convert('RGB')
            for label in ['Password','Verification code','Token']:
                x,y,w,h=field(s,label)['frame']
                assert png.getpixel((int(x+w/2),int(y+h/2)))==(17,17,17)
            auth=call('auth')
            assert auth['authenticated'] is None and {'password','verification_code'}<=set(auth['requirements'])
            checks.append('credential redaction, screenshot masks, honest auth hints')
            s=snap();call('click',element=field(s,'Delayed result')['id'])
            assert call('wait',condition='text',text='Ready after delay',timeout_ms=2000)['matched']
            assert not call('wait',condition='text',text='Never appears',timeout_ms=50)['matched']
            assert call('wait',condition='url',text='127.0.0.1',timeout_ms=50)['matched']
            s=snap();name=field(s,'Name')['id']
            assert call('wait',condition='enabled',element=name,timeout_ms=50)['matched']
            s=snap();call('click',element=field(s,'Hide name')['id'])
            # Detached/hidden wait uses a still-observed handle obtained before async mutation.
            call('wait',error='INVALID_WAIT',condition='text',text='x',timeout_ms=25001)
            checks.append('bounded waits and timeout result')
            tabs=call('tabs');original=tabs['tabs'][0]['id']
            for i in range(4):call('tabs',action='open',url=url+'/tab'+str(i))
            call('tabs',action='open',url=url+'/overflow',error='TAB_LIMIT')
            assert len(call('tabs')['tabs'])==5
            s=snap();call('click',element=field(s,'Popup fixture')['id'])
            deadline=time.monotonic()+3
            while True:
                tabs=call('tabs')
                assert len(tabs['tabs'])<=5
                if any(e['type']=='popup_blocked' for e in tabs['events']) or time.monotonic()>deadline:break
                time.sleep(.05)
            assert len(tabs['tabs'])==5 and any(e['type']=='popup_blocked' for e in tabs['events'])
            for tab in tabs['tabs']:
                if tab['id']!=original:call('tabs',action='close',tab=tab['id'])
            call('tabs',action='select',tab=original)
            assert len(call('tabs')['tabs'])==1
            checks.append('five-tab cap including popups; exact cleanup')
            s=snap();call('click',element=field(s,'Open modal')['id'])
            assert any(e['role']=='AXDialog' for e in snap()['elements'])
            call('tabs',action='open',url=url+'/other')
            s=snap()
            assert not any(e['role']=='AXDialog' for e in s['elements'])
            other=next(t['id'] for t in call('tabs')['tabs'] if t['selected'])
            call('tabs',action='select',tab=original)
            assert any(e['role']=='AXDialog' for e in snap()['elements'])
            call('key',key='escape')
            call('tabs',action='close',tab=other)
            checks.append('dialog remains owned by its tab')

            call('open',url=url+'/login')
            call('open',url=url+'/account')
            assert any('Signed in as fixture@example.test' in e.get('title','') for e in snap()['elements'])
            checks.append('normal fixture session authentication')
            report['engines'].append({'browser':browser,'checks':checks,'passed':True})
            print(json.dumps(report['engines'][-1]),flush=True)
        client.close()
        client=Client(options.entrypoint,'second-'+uuid.uuid4().hex,profile)
        for browser in ['chrome','safari']:
            client.call('open',browser=browser,url=url+'/account')
            s=client.call('snapshot',browser=browser)
            assert any('Signed in as fixture@example.test' in e.get('title','') for e in s['elements'])
        report['session_only_http_only_cookie_across_connections']=True
        status=client.call('status')
        saved=Path.home()/'.blacklabel/isolated-browser/profiles'/status['profile_id']/'chrome/session-cookies.json'
        assert saved.stat().st_mode & 0o777 == 0o600
        for browser in ['chrome','safari']:client.call('open',browser=browser,url=url+'/logout')
        client.close();client=Client(options.entrypoint,'after-logout-'+uuid.uuid4().hex,profile)
        for browser in ['chrome','safari']:
            client.call('open',browser=browser,url=url+'/account')
            s=client.call('snapshot',browser=browser)
            assert any(e.get('title')=='Login required' for e in s['elements'])
        report['logout_survives_restart_without_cookie_resurrection']=True
        isolated=Client(options.entrypoint,'unrelated-'+uuid.uuid4().hex)
        try:
            isolated.call('open',browser='chrome',url=url+'/account')
            s=isolated.call('snapshot',browser='chrome')
            assert any(e.get('title')=='Login required' for e in s['elements'])
        finally:
            isolated.close()
        report['default_chat_session_isolation']=True
        report['passed']=True
    finally:
        client.close()
        fixture.shutdown()
    if options.output:options.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'engines':len(report['engines']),'persistent_auth':True}),flush=True)


if __name__=='__main__':main()

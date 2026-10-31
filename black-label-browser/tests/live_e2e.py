"""Complete local provider workflow through public MCP calls; no production claims."""
import argparse
from email.parser import BytesParser
from email.policy import default
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import parse_qs
from live_workflow import Client

PRODUCTS=[]
DUPLICATE=False
class Provider(BaseHTTPRequestHandler):
    def send(self,body,status=200,headers=None):
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body.encode())
    def do_GET(self):
        account='fixture_session=local-e2e' in self.headers.get('Cookie','')
        if self.path=='/login':
            self.send('<h1>Sign in</h1><form action="/login" method="post"><input name="email" aria-label="Email"><input name="password" aria-label="Password" type="password"><button>Sign in</button></form>')
        elif self.path=='/code':
            self.send('<h1>Verification required</h1><form action="/code" method="post"><input name="code" aria-label="Verification code" autocomplete="one-time-code"><button>Verify</button></form>')
        elif self.path.startswith('/form') and account:
            duplicate='<input name="product" aria-label="Product name">' if DUPLICATE else ''
            self.send('''<h1>Signed in as e2e@example.test</h1><form action="/submitted" method="post" enctype="multipart/form-data">
              <input name="product" aria-label="Product name" required>'''+duplicate+'''
              <textarea name="description" aria-label="Description" required></textarea>
              <select name="category" aria-label="Category"><option>Other</option><option>Productivity</option></select>
              <label><input name="own" aria-label="Owned product" type="checkbox" required>Owned product</label>
              <input name="private" aria-label="Password" type="password">
              <input name="logo" aria-label="Logo" type="file" required>
              <button>Submit listing</button></form>''')
        elif self.path=='/submitted' and account:
            self.send('<h1>Signed in as e2e@example.test</h1><h2>Listing under review</h2><a href="/public">View published fixture</a>')
        elif self.path=='/public':
            self.send('<h1>Published fixture directory</h1>'+''.join('<p>'+p['product']+'</p>' for p in PRODUCTS))
        else:self.send('<h1>Sign in required</h1>')
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path=='/login':
            data=parse_qs(body.decode());assert data['email']==['e2e@example.test'] and data['password']==['synthetic-password']
            self.send('',303,{'Location':'/code'})
        elif self.path=='/code':
            assert parse_qs(body.decode())['code']==['246810']
            self.send('',303,{'Location':'/form','Set-Cookie':'fixture_session=local-e2e; HttpOnly; SameSite=Lax; Path=/'})
        elif self.path=='/submitted':
            assert 'fixture_session=local-e2e' in self.headers.get('Cookie','')
            msg=BytesParser(policy=default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\n\r\n'+body)
            data={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in msg.iter_parts()}
            PRODUCTS.append({'product':data['product'].decode(),'description':data['description'].decode(),'category':data['category'].decode(),'logo_hash':hashlib.sha256(data['logo']).hexdigest()})
            self.send('',303,{'Location':'/submitted'})
        else:self.send('Unknown',404)
    def log_message(self,*args):pass

def field(s,name):return next(e['id'] for e in s['elements'] if e.get('title')==name and e.get('tag') in ['input','textarea','select','button','a'])
def main():
    global DUPLICATE
    p=argparse.ArgumentParser();p.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py');p.add_argument('--output',type=Path);p.add_argument('--browser',choices=['chrome','safari'],default='chrome');args=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port);profile='e2e-'+uuid.uuid4().hex
    client=Client(args.entrypoint,'first',profile);report={'entrypoint':str(args.entrypoint),'browser':args.browser,'fixture_only':True,'checks':[]}
    def call(name,**kw):return client.call(name,browser=args.browser,**kw)
    def snap():return call('snapshot')
    with tempfile.TemporaryDirectory() as td:
        upload=Path(td)/'product.txt';upload.write_text('Genuine test fixture upload')
        try:
            call('open',url=url+'/login');s=snap()
            call('form',fields=[{'element':field(s,'Email'),'action':'fill','text':'e2e@example.test'},{'element':field(s,'Password'),'action':'fill','text':'synthetic-password'}]);s=snap()
            call('click',element=field(s,'Sign in'));s=snap()
            call('form',fields=[{'element':field(s,'Verification code'),'action':'fill','text':'246810'}]);s=snap()
            call('click',element=field(s,'Verify'));s=snap();assert 'Signed in as e2e@example.test' in s['text']
            report['checks'].append('password and one-time-code form login followed by observed account identity')
            fields=[{'element':field(s,'Product name'),'action':'fill','text':'E2E product'},{'element':field(s,'Description'),'action':'fill','text':'Real test-provider workflow.'},{'element':field(s,'Category'),'action':'select','labels':['Productivity']},{'element':field(s,'Owned product'),'action':'check','checked':True},{'element':field(s,'Password'),'action':'fill','text':'DO-NOT-CHECKPOINT'}]
            call('form',fields=fields);s=snap()
            call('checkpoint',action='save',id='bad',identity='Signed in as e2e@example.test',receipt_id='bad-final',fields=[field(s,'Password')],error='INVALID_CHECKPOINT_FIELD')
            assert call('checkpoint',action='list')['checkpoints']==[]
            call('checkpoint',action='save',id='product',identity='Signed in as e2e@example.test',receipt_id='product-final',fields=[field(s,n) for n in ['Product name','Description','Category','Owned product']])
            call('checkpoint',action='save',id='product',identity='Signed in as e2e@example.test',receipt_id='product-final',fields=[field(s,'Product name')],error='CHECKPOINT_EXISTS')
            status=client.call('status');saved=Path.home()/'.blacklabel/isolated-browser/profiles'/status['profile_id']/args.browser/'draft-checkpoints.json'
            assert saved.stat().st_mode & 0o777==0o600 and 'DO-NOT-CHECKPOINT' not in saved.read_text()
            report['checks'].append('explicit private draft excludes credentials and refuses silent overwrite')
            client.close();client=Client(args.entrypoint,'resumed',profile)
            listing=call('checkpoint',action='list');assert listing['checkpoints'][0]['fields_saved']==4 and 'E2E product' not in json.dumps(listing)
            call('open',url=url+'/form');s=snap();assert field(s,'Product name')
            assert next(e['value'] for e in s['elements'] if e.get('title')=='Product name')==''
            call('checkpoint',action='restore',id='product',identity='wrong identity',error='IDENTITY_MISMATCH')
            s=snap();assert next(e['value'] for e in s['elements'] if e.get('title')=='Product name')==''
            call('open',url=url+'/form-ambiguous');s=snap()
            call('checkpoint',action='restore',id='product',identity='Signed in as e2e@example.test',error='URL_MISMATCH')
            DUPLICATE=True
            call('open',url=url+'/form');snap()
            call('checkpoint',action='restore',id='product',identity='Signed in as e2e@example.test',error='TARGET_MISMATCH')
            assert all(e.get('value')=='' for e in snap()['elements'] if e.get('title') in ['Product name','Description'])
            DUPLICATE=False
            call('open',url=url+'/form');snap()
            result=call('checkpoint',action='restore',id='product',identity='Signed in as e2e@example.test');assert result['fields_confirmed']==4 and not result['submitted']
            s=snap();assert next(e['value'] for e in s['elements'] if e.get('title')=='Product name')=='E2E product'
            assert next(e['value'] for e in s['elements'] if e.get('title')=='Description')=='Real test-provider workflow.'
            report['checks'].append('connection restart retains authentication and restores four draft fields only after URL and identity checks')
            call('click',element=field(s,'Logo'));call('choose_file',path=str(upload));s=snap()
            receipt=call('click_verify',element=field(s,'Submit listing'),receipt_id='product-final',expect={'condition':'text','text':'Listing under review'},timeout_ms=3000)
            assert receipt['receipt']['state']=='verified';assert len(PRODUCTS)==1 and PRODUCTS[0]['logo_hash']==hashlib.sha256(upload.read_bytes()).hexdigest()
            s=snap();assert 'Signed in as e2e@example.test' in s['text'] and 'Listing under review' in s['text']
            call('open',url=url+'/public');s=snap();assert 'E2E product' in s['text']
            report['checks'].append('reattach file, submit once, verify provider receipt, independently read public fixture result')
            client.close();client=Client(args.entrypoint,'after-submit',profile)
            assert call('receipt',receipt_id='product-final')['receipt']['state']=='verified'
            call('open',url=url+'/form');s=snap()
            result=call('checkpoint',action='restore',id='product',identity='Signed in as e2e@example.test');assert not result['restored'] and result['status']=='action_recorded_reconcile'
            result=call('click_verify',element=field(s,'Submit listing'),receipt_id='product-final',expect={'condition':'text','text':'Listing under review'},timeout_ms=3000);assert not result['action_attempted'] and len(PRODUCTS)==1
            report['checks'].append('second restart blocks draft replay and submission duplication using durable receipt')
            call('checkpoint',action='delete',id='product');assert call('checkpoint',action='list')['checkpoints']==[]
            call('open',url=url+'/form');s=snap()
            call('form',fields=[{'element':field(s,'Product name'),'action':'fill','text':'Unconfirmed product'},{'element':field(s,'Description'),'action':'fill','text':'Unknown result regression'},{'element':field(s,'Owned product'),'action':'check','checked':True}]);s=snap()
            call('checkpoint',action='save',id='unknown',identity='Signed in as e2e@example.test',receipt_id='unknown-final',fields=[field(s,n) for n in ['Product name','Description','Owned product']])
            call('click',element=field(s,'Logo'));call('choose_file',path=str(upload));s=snap()
            result=call('click_verify',element=field(s,'Submit listing'),receipt_id='unknown-final',expect={'condition':'text','text':'Never appears'},timeout_ms=100)
            assert result['receipt']['state']=='unconfirmed' and len(PRODUCTS)==2
            snap();client.close();client=Client(args.entrypoint,'unknown-resume',profile)
            call('open',url=url+'/form');snap()
            result=call('checkpoint',action='restore',id='unknown',identity='Signed in as e2e@example.test')
            assert not result['restored'] and result['receipt_state']=='unconfirmed' and len(PRODUCTS)==2
            call('checkpoint',action='delete',id='unknown')
            report['checks'].append('unconfirmed final action survives restart and blocks draft replay; no extra provider submit')
            for tab in call('tabs')['tabs']:call('tabs',action='close',tab=tab['id'])
            assert call('tabs')['tabs']==[]
            report['checks'].append('completed draft removed and task tabs closed')
            report['passed']=True
        finally:
            client.close();server.shutdown()
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()

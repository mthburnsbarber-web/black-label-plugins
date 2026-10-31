"""Real browser capability checks, using local pages and synthetic data only."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import uuid

from live_workflow import Client


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/child'):
            body='<button onclick="this.textContent=\'Child saved\'">Shared action</button>'
        elif self.path.startswith('/capture'):
            body='''<input type="password" aria-label="Private password" value="synthetic-secret">
            <button style="position:absolute;left:1500px;top:100px" onclick="this.textContent='Wide clicked'">Wide action</button>
            <div style="height:2300px">Full page content</div>'''
        else:
            body='<h1>Long page</h1>' + ''.join(f'<button>Item {i}</button>' for i in range(850))
            body+='''<button onclick="this.textContent='Beyond saved'">Beyond truncation</button>
            <button>Shared action</button><iframe src="/child"></iframe>
            <div id="shadow"></div><script>document.getElementById('shadow').attachShadow({mode:'open'}).innerHTML='<button>Shadow action</button>';</script>'''
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
        self.wfile.write(('<!doctype html><title>Capability fixture</title>'+body).encode())

    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entrypoint',type=Path,default=Path(__file__).resolve().parents[1]/'server/server.py')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser',choices=['chrome','safari'],default='chrome')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port)
    client=Client(args.entrypoint,'capability-'+uuid.uuid4().hex)
    checks=[]
    try:
        client.call('open',browser=args.browser,url=url+'/dense')
        page=client.call('snapshot',browser=args.browser)
        assert page['truncated'] and not any(e.get('title')=='Beyond truncation' for e in page['elements'])
        found=client.call('find',browser=args.browser,query={'name':'Beyond truncation','role':'button'})
        assert found['match_count']==1 and len(found['matches'])==1,found
        client.call('click',browser=args.browser,element=found['matches'][0]['id'])
        found=client.call('find',browser=args.browser,query={'name':'Beyond saved','role':'button'})
        assert found['match_count']==1
        checks.append('semantic lookup reaches controls beyond a truncated page and retains exact identity')
        found=client.call('find',browser=args.browser,query={'name':'Shared action','role':'button'})
        assert found['match_count']==2 and {e['frame_index'] for e in found['matches']}=={0,1},found
        child=next(e for e in found['matches'] if e['frame_index']==1)
        client.call('click',browser=args.browser,element=child['id'])
        assert client.call('find',browser=args.browser,query={'name':'Child saved'})['match_count']==1
        checks.append('duplicate names remain explicit; iframe target is separately selectable')
        assert client.call('find',browser=args.browser,query={'name':'Shadow action'})['match_count']==1
        checks.append('open shadow-root controls are discoverable')
        found=client.call('find',browser=args.browser,query={'name':'Item','role':'button','exact':False,'limit':3})
        assert found['match_count']==850 and len(found['matches'])==3 and found['truncated']
        checks.append('partial matching has an exact total and bounded output')
        client.call('find',browser=args.browser,query={'name':'x','limit':101},error='INVALID_FIND')
        client.call('open',browser=args.browser,url=url+'/capture?private=must-not-be-in-metadata')
        client.call('viewport',browser=args.browser,width=1600,height=1100)
        page=client.call('snapshot',browser=args.browser)
        assert page['viewport']=={'width':1600,'height':1100}
        password=next(e for e in page['elements'] if e.get('type')=='password')
        assert password['value']=='[secure field]'
        with tempfile.TemporaryDirectory(prefix='browser-capture-') as temporary:
            file=Path(temporary)/'viewport.png'
            capture=client.call('capture',browser=args.browser,path=str(file))
            assert (capture['width'],capture['height'])==(1600,1100),capture
            assert '?' not in capture['source_url'] and 'private' not in capture['source_url']
            assert capture['sha256']==hashlib.sha256(file.read_bytes()).hexdigest()
            from PIL import Image
            with Image.open(file) as png:
                assert png.size==(1600,1100)
                x,y,w,h=password['frame'];assert png.convert('RGB').getpixel((int(x+w/2),int(y+h/2)))==(17,17,17)
            prior=file.read_bytes()
            client.call('capture',browser=args.browser,path=str(file),error='FILE_EXISTS')
            assert file.read_bytes()==prior
            full=client.call('capture',browser=args.browser,path=str(Path(temporary)/'full.png'),full_page=True)
            assert full['height']>1100 and full['width']==1600,full
        checks.append('native-resolution viewport/full-page captures have real dimensions, masks, hashes and no overwrite')
        found=client.call('find',browser=args.browser,query={'name':'Wide action'})
        x,y,w,h=found['matches'][0]['frame']
        client.call('click_at',browser=args.browser,x=x+w/2,y=y+h/2)
        assert client.call('find',browser=args.browser,query={'name':'Wide clicked'})['match_count']==1
        client.call('move',browser=args.browser,x=1601,y=100,error='INVALID_COORDINATES')
        checks.append('virtual input follows the actual wider viewport')
        original=next(t['id'] for t in client.call('tabs',browser=args.browser)['tabs'] if t['selected'])
        client.call('tabs',browser=args.browser,action='open',url=url+'/capture')
        assert client.call('snapshot',browser=args.browser)['viewport']=={'width':1440,'height':1000}
        client.call('tabs',browser=args.browser,action='select',tab=original)
        assert client.call('snapshot',browser=args.browser)['viewport']=={'width':1600,'height':1100}
        checks.append('resizing one task page preserves another page viewport')
        for tab in client.call('tabs',browser=args.browser)['tabs']:
            client.call('tabs',browser=args.browser,action='close',tab=tab['id'])
        assert client.call('tabs',browser=args.browser)['tabs']==[]
        result={'passed':True,'browser':args.browser,'entrypoint':str(args.entrypoint.resolve()),'checks':checks,'final_tabs':0}
        args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    finally:
        client.close();server.shutdown()


if __name__=='__main__':main()

"""Explicit local UI acceptance, creates only owned localhost fixture tabs.

Run manually during an authorized browser test. Never runs in unit discovery.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import select
import subprocess
import threading
import time
import uuid
import tempfile

class Page(BaseHTTPRequestHandler):
 def do_GET(self):
  page=b'''<!doctype html><html><head><title>Black Label Native Browser Test</title></head><body>
  <h1>Black Label native browser acceptance</h1>
  <label for="probe">Native test entry</label><input id="probe" aria-label="Native test entry">
  <button id="save" onclick="document.getElementById('result').textContent='Native receipt: ['+document.getElementById('probe').value+']'">Save native test</button>
  <p id="result" role="status">No test result yet</p>
  <label for="upload">Native test upload</label><input id="upload" type="file" aria-label="Native test upload">
  </body></html>'''
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page)
 def log_message(self,*args):pass

def main():
 helper=Path.home()/'Applications/Black Label Browser Bridge.app/Contents/MacOS/BrowserBridge'
 server=HTTPServer(('127.0.0.1',0),Page);threading.Thread(target=server.serve_forever,daemon=True).start()
 proc=subprocess.Popen([str(helper)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
 def call(command,**args):
  proc.stdin.write(json.dumps({'command':command,**args})+'\n');proc.stdin.flush()
  if not select.select([proc.stdout],[],[],30)[0]:raise RuntimeError('Native helper timeout')
  value=json.loads(proc.stdout.readline())
  if not value.get('ok'):raise RuntimeError(value.get('error'))
  return value['result']
 results={'native_status':call('status'),'browsers':[]}
 try:
  for browser in ['safari','chrome']:
   row={'browser':browser}
   try:
    url='http://127.0.0.1:'+str(server.server_port)+'/'+browser
    call('open',browser=browser,url=url)
    found=None
    for _ in range(40):
     snap=call('snapshot',browser=browser)
     fields=[e for e in snap['elements'] if e['role']=='AXTextField' and 'Native test entry' in (e.get('title','')+' '+e.get('description',''))]
     if fields:found=fields[0];break
     time.sleep(.3)
    if not found:
     row['diagnostic_elements']=[{k:e.get(k) for k in ['role','title','description','value']} for e in snap['elements'] if 'Native' in str(e)][:12]
     raise RuntimeError('Test field was not exposed in native accessibility tree')
    text='native-'+browser+'-'+str(uuid.uuid4())[:8]+' café — verified ✓'
    call('fill',browser=browser,element=found['id'],text=text)
    snap=call('snapshot',browser=browser)
    buttons=[e for e in snap['elements'] if e['role']=='AXButton' and 'Save native test' in str(e)]
    if not buttons:raise RuntimeError('Save button missing')
    call('click',browser=browser,element=buttons[0]['id'])
    for _ in range(6):
     snap=call('snapshot',browser=browser)
     row['text_fill_and_submit_verified']=any('Native receipt: ['+text+']' in str(e) for e in snap['elements'])
     if row['text_fill_and_submit_verified']:break
     time.sleep(.15)
    # Clearing a field must change the actual page value, not only select text.
    clear_field=next(e for e in snap['elements'] if e['role']=='AXTextField' and 'Native test entry' in (e.get('title','')+' '+e.get('description','')))
    call('fill',browser=browser,element=clear_field['id'],text='')
    snap=call('snapshot',browser=browser)
    clear_button=next(e for e in snap['elements'] if e['role']=='AXButton' and 'Save native test' in str(e))
    call('click',browser=browser,element=clear_button['id'])
    for _ in range(8):
     snap=call('snapshot',browser=browser)
     row['empty_field_submit_verified']=any(e.get('value')=='Native receipt: []' or e.get('title')=='Native receipt: []' for e in snap['elements'])
     if row['empty_field_submit_verified']:break
     time.sleep(.15)
    if not row['empty_field_submit_verified']:
     row['clear_diagnostic']=[e for e in snap['elements'] if 'Native receipt' in str(e) or 'Native test entry' in str(e)]
     raise RuntimeError('Empty fill did not clear actual page input')
    row['extension_used']=False;row['apple_events_used']=False;row['fixture_url']=url
    if not row['text_fill_and_submit_verified']:
     row['diagnostic_elements']=[{k:e.get(k) for k in ['role','title','description','value']} for e in snap['elements'] if 'Native' in str(e) or text in str(e)][:15]
     raise RuntimeError('Result did not match submitted text')
    with tempfile.TemporaryDirectory(prefix='bl-native-fixture-') as tmp:
     image=Path(tmp)/'capture.png'
     call('screenshot',browser=browser,path=str(image))
     row['screenshot_verified']=image.is_file() and image.read_bytes().startswith(b'\x89PNG')
     # File input names differ across browser AX implementations; use the
     # observed button exposed alongside the unique fixture label.
     uploads=[e for e in snap['elements'] if e['role']=='AXButton' and any(s in str(e).lower() for s in ['choose file','choose files','native test upload'])]
     if not uploads:
      row['upload_diagnostic']=[{k:e.get(k) for k in ['role','title','description','value']} for e in snap['elements'] if 'upload' in str(e).lower() or 'file' in str(e).lower()][:12]
      raise RuntimeError('Native upload control not exposed')
     call('click',browser=browser,element=uploads[0]['id'])
     snap=call('snapshot',browser=browser)
     upload=Path(tmp)/'native-upload-proof.txt';upload.write_text('Native file chooser proof')
     call('choose_file',browser=browser,path=str(upload))
     for _ in range(6):
      snap=call('snapshot',browser=browser)
      opens=[e for e in snap['elements'] if e['role']=='AXButton' and e.get('title') in ['Open','Upload','Choose'] and e.get('enabled',True)]
      if opens:break
      time.sleep(.2)
     if not opens:raise RuntimeError('Native file chooser Open button not exposed')
     call('click',browser=browser,element=opens[0]['id'])
     for _ in range(5):
      snap=call('snapshot',browser=browser)
      row['file_selection_verified']=any('native-upload-proof.txt' in str(e) for e in snap['elements'])
      if row['file_selection_verified']:break
      time.sleep(.15)
     if not row['file_selection_verified']:raise RuntimeError('Selected file was not read back in page')
   except Exception as exc:row['error']=str(exc)
   results['browsers'].append(row)
 finally:
  proc.terminate();proc.wait(timeout=5);server.shutdown()
 out=Path.home()/'.blacklabel/native-browser/live-acceptance.json'
 out.write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps(results,indent=2))
 if not all(r.get('text_fill_and_submit_verified') and r.get('empty_field_submit_verified') and r.get('screenshot_verified') and r.get('file_selection_verified') for r in results['browsers']):raise SystemExit(1)

if __name__=='__main__':main()

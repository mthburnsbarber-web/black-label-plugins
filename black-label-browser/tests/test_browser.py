import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from mcp_stdio import validate
import server

class BrowserTests(unittest.TestCase):
 def test_no_extension_or_cdp_dependency(self):
  source=(ROOT/'native/BrowserBridge.swift').read_text()
  self.assertIn('AXUIElement',source);self.assertNotIn('9222',source)
  self.assertNotIn('AppleScript',source);self.assertIn('STALE_ELEMENT',source)
 def test_missing_browser_and_unknown_fields_rejected(self):
  spec=next(t for t in server.TOOLS if t['name']=='browser_fill')
  for args in [{},{'browser':'edge','element':'1','text':'ok'},{'browser':'chrome','element':'1','text':'ok','shell':'run'}]:
   with self.assertRaises(ValueError):validate(args,spec['inputSchema'])
 def test_otp_filters_sender_service_and_time(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'messages.db';db=sqlite3.connect(p)
   db.executescript('CREATE TABLE handle(id TEXT); CREATE TABLE message(text TEXT,date INTEGER,handle_id INTEGER,is_from_me INTEGER);')
   now=dt.datetime.now(dt.timezone.utc);stamp=int((now.timestamp()-978307200)*1e9)
   db.execute('INSERT INTO handle VALUES(?)',('12345',));db.execute('INSERT INTO handle VALUES(?)',('99999',))
   db.executemany('INSERT INTO message VALUES(?,?,?,0)',[('Example verification code: 123456',stamp,1),('Other verification code: 444444',stamp,1),('Example verification code: 888888',stamp,2),('Example verification code: 111111',stamp-int(1e12),1)])
   db.commit();db.close()
   args={'sender':'12345','service':'Example','after':(now-dt.timedelta(minutes=2)).isoformat()}
   result=server.verification_text(args,p)
   self.assertEqual([x['code'] for x in result['matches']],['123456'])
   self.assertNotIn('body',json.dumps(result))
   del args['sender']
   result=server.verification_text(args,p)
   self.assertEqual(result['status'],'ambiguous_senders');self.assertEqual(result['matches'],[])
 def test_old_otp_request_rejected(self):
  with self.assertRaises(ValueError):server.verification_text({'sender':'12345','service':'Example','after':'2000-01-01T00:00:00Z'})
 def test_email_route_is_not_reported_as_inbox_execution(self):
  result=server.dispatch('browser_email_code_route',{'provider':'gmail','sender':'verify@example.com','service':'Example','after':dt.datetime.now(dt.timezone.utc).isoformat()})
  self.assertFalse(result['executed']);self.assertIn('from%3Averify%40example.com',result['url'])
 def test_all_webmail_routes_and_custom_credential_rejection(self):
  args={'sender':'verify@example.com','service':'Example','after':dt.datetime.now(dt.timezone.utc).isoformat()}
  for provider in ['gmail','outlook','icloud','yahoo','proton','fastmail']:
   result=server.dispatch('browser_email_code_route',{**args,'provider':provider})
   self.assertTrue(result['url'].startswith('https://'));self.assertFalse(result['executed'])
  with self.assertRaises(ValueError):server.dispatch('browser_email_code_route',{**args,'provider':'custom','webmail_url':'https://secret@example.com/'})
 def test_future_email_window_rejected(self):
  args={'provider':'gmail','sender':'verify@example.com','service':'Example','after':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=1)).isoformat()}
  with self.assertRaises(ValueError):server.dispatch('browser_email_code_route',args)
 def test_busy_inbox_does_not_hide_matching_code(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'messages.db';db=sqlite3.connect(p)
   db.executescript('CREATE TABLE handle(id TEXT); CREATE TABLE message(text TEXT,date INTEGER,handle_id INTEGER,is_from_me INTEGER); INSERT INTO handle VALUES("12345");')
   now=dt.datetime.now(dt.timezone.utc);stamp=int((now.timestamp()-978307200)*1e9)
   db.execute('INSERT INTO message VALUES(?,?,1,0)',('Example verification code: 123456',stamp-100,))
   db.executemany('INSERT INTO message VALUES(?,?,1,0)', [('Unrelated recent message',stamp+i) for i in range(40)])
   db.commit();db.close()
   result=server.verification_text({'service':'Example','after':(now-dt.timedelta(minutes=1)).isoformat()},p)
   self.assertEqual(result['matches'][0]['code'],'123456')
 def test_native_actions_serialize_across_browsers(self):
  import fcntl
  with tempfile.TemporaryDirectory() as tmp, patch.object(server.Path,'home',return_value=Path(tmp)):
   directory=Path(tmp)/'.blacklabel/native-browser';directory.mkdir(parents=True)
   with (directory/'desktop-input.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for browser in ['safari','chrome']:
     with self.assertRaisesRegex(ValueError,'in flight'):server.native('key',{'browser':browser,'key':'return'})
 def test_write_tools_report_destructive_potential(self):
  for t in server.TOOLS:
   if t['name'] in {'browser_click','browser_fill','browser_type','browser_key','browser_click_at'}:
    self.assertTrue(t['annotations']['destructiveHint'])
 def test_mcp_protocol_roundtrip(self):
  lines=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'browser_fill','arguments':{'browser':'no'}}}]
  p=subprocess.run([sys.executable,str(ROOT/'server/server.py')],input='\n'.join(map(json.dumps,lines))+'\n',capture_output=True,text=True,check=True)
  out=list(map(json.loads,p.stdout.splitlines()));self.assertEqual(len(out),3)
  self.assertEqual(out[0]['result']['serverInfo']['name'],'black-label-browser')
  self.assertEqual(len(out[1]['result']['tools']),14);self.assertTrue(out[2]['result']['isError'])

if __name__=='__main__':unittest.main()

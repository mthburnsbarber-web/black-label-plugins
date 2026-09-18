import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from core import Presence

class PresenceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name);self.p=Presence(self.path)
  self.run=self.p.run('task','Publish distinct posts with real photos',sites=['x','linkedin'])['run']['id']
  self.media=self.path/'demo.png';self.media.write_bytes(b'test fixture image bytes')
 def tearDown(self):self.p.close();self.temp.cleanup()
 def stage(self,site='x',body='Example Sign lets a recipient sign a document without creating an account. Here is the signer workflow.'):
  return self.p.stage(self.run,site,'@example',body,'Show the actual recipient signing workflow',[{'claim':'Signer needs no account','url':'https://example.com/sign'}],[str(self.media)])
 def reviewed(self):
  content=self.stage();self.assertTrue(content['staged'])
  self.p.review(content['content_id'],content['hash'],'Observed the live signer workflow and checked the published product page.','Inspected screenshot crop, real controls and readable text.','This post shows the recipient view, distinct from prior sender demos.')
  self.p.account('x','@example','https://x.com/example','chrome','signed_in','Observed authenticated account menu @example.')
  return content
 def test_all_sites_and_no_bundled_identities(self):
  self.assertEqual(self.p.catalog()['counts'],{'active':44,'held':8,'excluded':3,'conditional':2})
  self.assertEqual(len(self.p.platforms),57)
  self.assertTrue(all(not p['account_candidates'] for p in self.p.platforms))
  for site in self.p.platforms:self.assertTrue(site['requirements'])
 def test_resume_preserves_scope_and_corrections(self):
  self.p.amend(self.run,'Include photos on every promotional post.')
  self.p.close();self.p=Presence(self.path)
  result=self.p.run('task','go',sites=['reddit'])
  self.assertEqual(result['run']['id'],self.run)
  self.assertEqual(result['run']['request'],'Publish distinct posts with real photos')
  self.assertEqual(len(result['run']['corrections']),1)
  self.assertEqual({x['site'] for x in result['remaining']},{'x','linkedin'})
 def test_one_site_dependency_does_not_stop_other(self):
  first=self.p.next(self.run)['next']
  self.p.record(first['id'],first['lease'],'needs_user','Device approval shown in actual browser.')
  second=self.p.next(self.run)['next'];self.assertNotEqual(first['site'],second['site'])
 def test_no_verified_without_evidence(self):
  t=self.p.next(self.run)['next']
  with self.assertRaises(ValueError):self.p.record(t['id'],t['lease'],'verified','Clicked button')
 def test_stale_lease_and_cross_run_site_lock(self):
  t=self.p.next(self.run)['next'];other=Presence(self.path)
  try:
   run=other.run('other','Another request',sites=[t['site']])['run']['id']
   self.assertIsNone(other.next(run)['next'])
   with self.p.db:self.p.db.execute('UPDATE tasks SET lease_until=0 WHERE id=?',(t['id'],))
   with self.assertRaises(ValueError):self.p.record(t['id'],t['lease'],'retry','retry')
   other.next(run)
   self.assertEqual(self.p.row('tasks',t['id'])['status'],'uncertain')
  finally:other.close()
 def test_generic_filler_missing_media_and_duplicates(self):
  bad=self.stage(body='Unlock the power of our revolutionary platform and transform your workflow with game-changing AI.')
  self.assertFalse(bad['staged'])
  missing=self.p.stage(self.run,'x','@example','Example Sign lets recipients sign without a new account.','Specific signing workflow',[{'claim':'Signer flow','url':'https://example.com/sign'}],[])
  self.assertFalse(missing['staged'])
  self.assertTrue(self.stage()['staged']);self.assertFalse(self.stage()['staged'])
 def test_media_mutation_invalidates_review(self):
  c=self.reviewed();self.media.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.p.prepare(c['content_id'])
 def test_draft_does_not_publish(self):
  run=self.p.run('draft','Draft only','draft',['x'])['run']['id']
  c=self.p.stage(run,'x','other','Example Sign sends a document for signature without a recipient account.','Actual document signing workflow',[{'claim':'Signer flow','url':'https://example.com/sign'}],[str(self.media)])
  self.p.review(c['content_id'],c['hash'],'Observed actual live source claim and signer flow.','Inspected real image, branding and readable screenshot.','Different demonstration than existing material.')
  with self.assertRaises(ValueError):self.p.prepare(c['content_id'])
 def test_unknown_submission_never_republishes(self):
  c=self.reviewed();pub=self.p.prepare(c['content_id']);self.assertTrue(pub['publish'])
  self.p.publication_result(pub['publication_id'],'uncertain','@example','Composer timed out after submission.')
  self.assertFalse(self.p.prepare(c['content_id'])['publish'])
 def test_exact_post_verification_and_wrong_identity(self):
  c=self.reviewed();pub=self.p.prepare(c['content_id']);body=self.p.row('content',c['content_id'])['body']
  for identity,readback,url in [('wrong',body,'https://x.com/example/status/123'),('@example','Clicked Post','https://x.com/example/status/123'),('@example',body,'https://evil.example/post')]:
   with self.assertRaises(ValueError):self.p.publication_result(pub['publication_id'],'verified',identity,readback,True,url)
  result=self.p.publication_result(pub['publication_id'],'verified','@example',body,True,'https://x.com/example/status/123')
  self.assertEqual(result['receipt']['outcome'],'verified')
  self.assertFalse(self.p.status(self.run)['complete'])
 def test_held_excluded_and_secret_records_rejected(self):
  for site in ['gumroad','behance']:
   with self.assertRaises(ValueError):self.p.run(site,'Publish',sites=[site])
  with self.assertRaises(ValueError):self.p.amend(self.run,'password=do-not-record-this')
 def test_secrets_in_claims_and_unverified_receipts_rejected(self):
  with self.assertRaises(ValueError):
   self.p.stage(self.run,'x','example','A concrete example post with sufficient detail.','A specific useful demonstration',[{'claim':'password=secret','url':'https://example.com'}],[str(self.media)])
  c=self.reviewed();pub=self.p.prepare(c['content_id'])
  with self.assertRaises(ValueError):self.p.publication_result(pub['publication_id'],'uncertain','example','Checking result',False,'https://example.com?token=secret')
 def test_existing_state_directory_is_private(self):
  import os
  os.chmod(self.path,0o755);other=Presence(self.path)
  try:self.assertEqual(self.path.stat().st_mode & 0o777,0o700)
  finally:other.close()
 def test_export_has_hash_and_remaining_work(self):
  result=self.p.export(self.run);self.assertTrue(Path(result['path']).is_file());self.assertFalse(result['complete'])
  self.assertEqual(len(result['sha256']),64)

if __name__=='__main__':unittest.main()

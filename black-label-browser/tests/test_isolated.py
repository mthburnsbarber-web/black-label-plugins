import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import isolated
import server


class IsolationTests(unittest.TestCase):
    def test_every_browser_entry_point_uses_isolated_driver(self):
        for command in ['status','open','snapshot','focus_window','click','fill','type','key','click_at','scroll','choose_file','tabs','form','wait','auth','hover','move','click_verify','receipt','find','viewport','capture','checkpoint']:
            with self.subTest(command=command), patch.object(server, 'native') as desktop, patch.object(isolated, 'call', return_value={'headless':True}) as hidden:
                self.assertTrue(server.dispatch('browser_'+command, {'browser':'chrome'})['headless'])
                hidden.assert_called_once_with(command, {'browser':'chrome'})
                desktop.assert_not_called()

    def test_screenshot_only_reads_engine_render(self):
        def render(command,args):
            self.assertEqual(command, 'screenshot')
            Path(args['path']).write_bytes(b'\x89PNG\r\n\x1a\n')
        with patch.object(server, 'native') as desktop, patch.object(isolated, 'call', side_effect=render):
            result=server.dispatch('browser_screenshot', {'browser':'chrome'})
            self.assertEqual(result['_mcp_content'][0]['mimeType'], 'image/png')
            desktop.assert_not_called()

    def test_timeout_response_cannot_be_misattributed_or_mutation_repeated(self):
        process=Mock();process.poll.return_value=None
        process.stdout=io.StringIO(json.dumps({'ok':True,'result':{'old':True}})+'\n'+json.dumps({'ok':True,'result':{'current':True}})+'\n')
        with patch.object(isolated,'_process',process), patch.object(isolated,'_pending',True), patch.object(isolated,'_reconcile_required',True), patch.object(isolated.select,'select',return_value=([process.stdout],[],[])):
            with self.assertRaisesRegex(ValueError,'RECONCILIATION_REQUIRED'):
                isolated.call('click',{'browser':'chrome','element':'stale'})
            process.stdin.write.assert_not_called()
            result=isolated.call('snapshot',{'browser':'chrome'})
            self.assertTrue(result['current']);self.assertFalse(isolated._reconcile_required)

    def test_unfinished_timed_out_action_is_not_replayed(self):
        process=Mock()
        with patch.object(isolated,'_process',process),patch.object(isolated,'_pending',True),patch.object(isolated.select,'select',return_value=([],[],[])):
            with self.assertRaisesRegex(ValueError,'ACTION_PENDING'):
                isolated.call('snapshot',{'browser':'chrome'})
            process.stdin.write.assert_not_called()

    def test_closed_worker_requires_reconciliation_before_another_mutation(self):
        process=Mock();process.poll.return_value=None;process.stdout=io.StringIO('')
        with patch.object(isolated,'_process',process),patch.object(isolated,'_pending',False),patch.object(isolated,'_reconcile_required',False),patch.object(isolated.select,'select',return_value=([process.stdout],[],[])):
            with self.assertRaisesRegex(ValueError,'BROWSER_CLOSED'):
                isolated.call('click',{'browser':'chrome','element':'observed'})
            self.assertTrue(isolated._reconcile_required)
            process.stdin.write.reset_mock()
            with self.assertRaisesRegex(ValueError,'RECONCILIATION_REQUIRED'):
                isolated.call('click',{'browser':'chrome','element':'observed'})
            process.stdin.write.assert_not_called()

    def test_profile_names_cannot_escape_or_be_empty(self):
        for name in ['', '../personal', '/tmp/profile', 'profile with spaces']:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'INVALID_PROFILE'):
                isolated.acquire_profile(name, named=True)

    def test_unconfirmed_verified_click_requires_snapshot_but_receipt_remains_readable(self):
        process=Mock();process.poll.return_value=None
        process.stdout=io.StringIO(json.dumps({'ok':True,'result':{'receipt':{'state':'unconfirmed'}}})+'\n'+json.dumps({'ok':True,'result':{'receipt':{'state':'unconfirmed'}}})+'\n')
        with patch.object(isolated,'_process',process),patch.object(isolated,'_pending',False),patch.object(isolated,'_reconcile_required',False),patch.object(isolated.select,'select',return_value=([process.stdout],[],[])):
            isolated.call('click_verify',{'browser':'chrome'})
            with self.assertRaisesRegex(ValueError,'RECONCILIATION_REQUIRED'):
                isolated.call('click',{'browser':'chrome'})
            self.assertEqual(isolated.call('receipt',{'browser':'chrome','receipt_id':'one'})['receipt']['state'],'unconfirmed')

    def test_partial_forms_block_further_mutation_until_snapshot(self):
        process=Mock();process.poll.return_value=None
        process.stdout=io.StringIO(json.dumps({'ok':False,'error':'ISOLATED_FORM_PARTIAL: 1 of 2 fields confirmed'})+'\n')
        with patch.object(isolated,'_process',process),patch.object(isolated,'_pending',False),patch.object(isolated,'_reconcile_required',False),patch.object(isolated.select,'select',return_value=([process.stdout],[],[])):
            with self.assertRaisesRegex(ValueError,'FORM_PARTIAL'):
                isolated.call('form',{'browser':'chrome','fields':[]})
            with self.assertRaisesRegex(ValueError,'RECONCILIATION_REQUIRED'):
                isolated.call('tabs',{'browser':'chrome','action':'close','tab':'one'})

    def test_helper_has_no_owner_desktop_apis(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'native/BrowserBridge.swift').read_text()
        worker=(root/'server/headless.mjs').read_text()
        for symbol in ['import AppKit','AXUIElement','CGEvent(','screencapture','activate(','bringToFront(']:
            self.assertNotIn(symbol,source)
            self.assertNotIn(symbol,worker)
        self.assertIn('headless: true',worker)
        self.assertNotIn('remote-debugging-port',worker)

    def test_installer_preserves_other_browser_runtimes(self):
        source=(Path(__file__).resolve().parents[1]/'install.py').read_text()
        self.assertIn("'PLAYWRIGHT_SKIP_BROWSER_GC':'1'",source)


if __name__=='__main__':unittest.main()

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import isolated
import server
import session_refs


class SessionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {'BL_BROWSER_STATE_ROOT': str(self.root), 'BL_BROWSER_PRODUCT': 'utah'}
        self.addCleanup(self.temp.cleanup)

    def test_returned_reference_reopens_the_exact_store_without_hashing(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        identifier = created['reference'].removeprefix('acct_')
        binding = session_refs.resolve(created['reference'], self.env)
        self.assertEqual(binding['id'], identifier)
        self.assertNotEqual(binding['id'], hashlib.sha256(created['reference'].encode()).hexdigest()[:24])
        self.assertEqual(session_refs.worker_environment(binding, {'generation': 1})['BL_BROWSER_ACCOUNT_REF'], identifier)

    def test_double_hash_regression_from_the_recorded_failure(self):
        # 2026-10-30: the returned digest was passed as a name and hashed into cc6de2de….
        returned = 'bbbff28cb00fc34443ac2a73'
        self.assertEqual(hashlib.sha256(returned.encode()).hexdigest()[:24], 'cc6de2de013819a4e7493fcc')
        with self.assertRaisesRegex(ValueError, 'SESSION_REFERENCE_PASSED_AS_NAME'):
            session_refs.from_environment({'BL_BROWSER_SESSION': returned}, 1)
        (self.root / 'sessions' / returned).mkdir(parents=True)
        self.assertEqual(session_refs.resolve('session:' + returned, self.env)['id'], returned)

    def test_create_is_idempotent_per_account_and_separates_identities(self):
        first = session_refs.create_session('github', 'founder', role='founder', env=self.env)
        again = session_refs.create_session('github', 'founder', env=self.env)
        company = session_refs.create_session('github', 'company', role='company', env=self.env)
        other_workspace = session_refs.create_session('github', 'founder', workspace='customer-a', env=self.env)
        self.assertTrue(first['created'])
        self.assertFalse(again['created'])
        self.assertEqual(first['reference'], again['reference'])
        self.assertEqual(len({first['reference'], company['reference'], other_workspace['reference']}), 3)

    def test_missing_reference_never_creates_a_replacement(self):
        with self.assertRaisesRegex(ValueError, 'SESSION_NOT_FOUND'):
            session_refs.resolve('acct_' + 'a' * 24, self.env)
        self.assertFalse((self.root / 'accounts' / ('a' * 24)).exists())
        created = session_refs.create_session('github', 'founder', env=self.env)
        identifier = created['reference'].removeprefix('acct_')
        (self.root / 'accounts' / identifier / 'reference.json').unlink()
        with self.assertRaisesRegex(ValueError, 'SESSION_NOT_FOUND'):
            session_refs.create_session('github', 'founder', env=self.env)

    def test_replacing_a_lost_store_is_explicit_and_never_touches_one_that_exists(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        identifier = created['reference'].removeprefix('acct_')
        self.assertEqual(session_refs.create_session('github', 'founder', env=self.env, replace_missing=True)['reference'], created['reference'])
        (self.root / 'accounts' / identifier / 'reference.json').unlink()
        replaced = session_refs.create_session('github', 'founder', env=self.env, replace_missing=True)
        self.assertTrue(replaced['created'])
        self.assertNotEqual(replaced['reference'], created['reference'])

    def test_paths_and_guessed_values_are_refused(self):
        for value in ['/tmp/profile', '../other', 'acct_short', 'founder', 'acct_' + 'a' * 24 + '/..', None, 7]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'INVALID_SESSION_REFERENCE'):
                session_refs.resolve(value, self.env)
        for field in ['../up', 'a/b', '', ' padded ']:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'INVALID_ACCOUNT_BINDING'):
                session_refs.create_session('github', field, env=self.env)

    def test_other_product_cannot_open_the_reference(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        with self.assertRaisesRegex(ValueError, 'SESSION_SCOPE_DENIED'):
            session_refs.resolve(created['reference'], {**self.env, 'BL_BROWSER_PRODUCT': 'ace'})

    def test_busy_reports_the_lease_and_generations_only_go_up(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        binding = session_refs.resolve(created['reference'], self.env)
        first, lease = session_refs.acquire(binding, self.env, 'task-1')
        self.assertEqual(lease['generation'], 1)
        with self.assertRaises(ValueError) as caught:
            session_refs.acquire(binding, self.env, 'task-2')
        message = str(caught.exception)
        self.assertTrue(message.startswith('ISOLATED_PROFILE_BUSY'))
        self.assertEqual(json.loads(message[message.index('{'):])['generation'], 1)
        first.close()
        second, lease = session_refs.acquire(binding, self.env, 'task-2')
        self.assertEqual(lease['generation'], 2)
        second.close()

    def test_a_closing_worker_gets_a_short_wait_and_a_held_lease_still_stays_busy(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        binding = session_refs.resolve(created['reference'], self.env)
        holder, _ = session_refs.acquire(binding, self.env, 'closing')
        timer = threading.Timer(0.4, holder.close)
        timer.start()
        second, lease = session_refs.acquire(binding, self.env, 'next', wait_seconds=5)
        self.assertEqual(lease['generation'], 2)
        with self.assertRaisesRegex(ValueError, 'ISOLATED_PROFILE_BUSY'):
            session_refs.acquire(binding, self.env, 'third', wait_seconds=0.3)
        second.close()
        timer.join()

    def test_corrupt_record_is_a_typed_failure_and_is_left_in_place(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        path = self.root / 'accounts' / created['reference'].removeprefix('acct_') / 'reference.json'
        path.write_text('{not json')
        with self.assertRaisesRegex(ValueError, 'SESSION_RECORD_INVALID'):
            session_refs.resolve(created['reference'], self.env)
        self.assertEqual(path.read_text(), '{not json')

    def test_named_profile_stays_a_separate_explicit_operation(self):
        binding = session_refs.named('black-label-social')
        self.assertEqual(binding['id'], 'e98eb4fa7349894cbbf584c4')
        self.assertEqual(binding['reference'], 'profile:e98eb4fa7349894cbbf584c4')
        self.assertEqual(session_refs.from_environment({'BL_BROWSER_PROFILE': 'black-label-social'}, 1), binding)

    def test_records_hold_no_paths_or_secret_fields(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        self.assertFalse({'path', 'directory', 'password', 'token', 'cookie'} & set(created))

    def test_broker_commands_are_not_model_tools(self):
        names = {tool['name'] for tool in server.TOOLS}
        self.assertIn('browser_session', names)
        self.assertFalse({'browser_bound_fill', 'browser_page_meta'} & names)

    def test_rebind_is_refused_while_an_outcome_is_unknown(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        with patch.dict(os.environ, self.env), patch.object(isolated, '_pending', False), patch.object(isolated, '_reconcile_required', True):
            with self.assertRaisesRegex(ValueError, 'RECONCILIATION_REQUIRED'):
                isolated.session({'action': 'reopen', 'reference': created['reference']})

    def test_busy_target_leaves_the_connection_unchanged(self):
        created = session_refs.create_session('github', 'founder', env=self.env)
        holder, _ = session_refs.acquire(session_refs.resolve(created['reference'], self.env), self.env, 'other')
        current = Mock()
        with patch.dict(os.environ, self.env), patch.object(isolated, '_process', current), patch.object(isolated, '_binding', None), \
             patch.object(isolated, '_pending', False), patch.object(isolated, '_reconcile_required', False):
            with self.assertRaisesRegex(ValueError, 'ISOLATED_PROFILE_BUSY'):
                isolated.session({'action': 'reopen', 'reference': created['reference']})
            current.stdin.close.assert_not_called()
        holder.close()


if __name__ == '__main__':
    unittest.main()

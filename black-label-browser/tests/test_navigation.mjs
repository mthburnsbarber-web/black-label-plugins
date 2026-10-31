import test from 'node:test';
import assert from 'node:assert/strict';
import {retryAfter, accessDiagnostics, authHints, assertNavigationAllowed} from '../server/workflow.mjs';

test('Retry-After accepts seconds and HTTP dates without trusting arbitrary text', () => {
  const now = Date.parse('2026-10-29T05:00:00Z');
  assert.equal(retryAfter('120', now), now + 120000);
  assert.equal(retryAfter('Thu, 29 Oct 2026 05:01:00 GMT', now), now + 60000);
  assert.equal(retryAfter('Wed, 21 Oct 2015 07:28:00 GMT', now), now);
  for (const value of ['', '-1', '1.5', 'tomorrow', '0'.repeat(20)+'e2']) assert.equal(retryAfter(value, now), null);
});

test('challenge, denial, rate limit, HTTP error and network errors stay distinct', () => {
  const cases = [
    [{document:{status:403,challenge:true}}, '', 'challenge'],
    [{document:{status:200}}, 'Performing security verification', 'challenge'],
    [{document:{status:403}}, 'Forbidden', 'access_denied'],
    [{document:{status:429}}, 'Wait before retrying', 'rate_limited'],
    [{document:{status:503}}, 'Unavailable', 'http_error'],
    [{failure:'certificate_or_tls'}, '', 'navigation_error'],
    [{document:{status:200}}, 'Article about captcha integrations', 'none_detected']
  ];
  for (const [record,text,kind] of cases) assert.equal(accessDiagnostics(record,'',text).kind,kind);
  const challenge = accessDiagnostics({document:{status:403,challenge:true}}, '', 'Opaque challenge');
  assert.ok(authHints([], '', challenge).requirements.includes('human_verification'));
  assert.equal(authHints([], '', challenge).authenticated, null);
});

test('cooldown prevents early navigation only for the affected origin', () => {
  const limits = new Map([['https://one.example',{until:Date.now()+60000,source:'server_retry_after'}]]);
  assert.throws(()=>assertNavigationAllowed(limits,'https://one.example/other'),/ISOLATED_RETRY_LATER/);
  assert.doesNotThrow(()=>assertNavigationAllowed(limits,'https://two.example/'));
  limits.get('https://one.example').until = Date.now()-1;
  assert.doesNotThrow(()=>assertNavigationAllowed(limits,'https://one.example/'));
  assert.equal(limits.size,0);
});

test('Google HTTP 200 rejection is failed authentication without guessing its cause', () => {
  for (const path of ['/v3/signin/rejected', '/signin/rejected/']) {
    const access = accessDiagnostics({document:{status:200,url:'https://accounts.google.com'+path}},
      'Sign in - Google Accounts', 'Couldn’t sign you in\nThis browser or app may not be secure.');
    assert.equal(access.kind, 'authentication_rejected');
    assert.deepEqual(access.evidence, ['google_signin_rejected_page']);
    assert.match(access.next, /reason is unverified/);
    const auth = authHints([], '', access);
    assert.equal(auth.status, 'authentication_rejected');
    assert.deepEqual(auth.requirements, ['provider_rejected_signin']);
    assert.equal(auth.authenticated, null);
  }
  // The endpoint remains a rejection with localized text or an empty body.
  assert.equal(accessDiagnostics({document:{status:200,url:'https://accounts.google.com/v3/signin/rejected'}}, '', '').kind,
    'authentication_rejected');
  for (const url of ['https://example.test/v3/signin/rejected',
    'https://accounts.google.com.example.test/v3/signin/rejected',
    'https://accounts.google.com/v3/signin/identifier']) {
    assert.equal(accessDiagnostics({document:{status:200,url}}, '',
      'Article: This browser or app may not be secure.').kind, 'none_detected');
  }
  assert.equal(accessDiagnostics({failure:'network',document:{status:200,url:'https://accounts.google.com/v3/signin/rejected'}}).kind,
    'navigation_error');
  assert.equal(accessDiagnostics({document:{status:400,url:'https://accounts.google.com/v3/signin/rejected'}}, '',
    'The server cannot process the request because it is malformed.').kind, 'http_error');
});

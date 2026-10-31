import test from 'node:test';
import assert from 'node:assert/strict';
import {classifyAccess, settleNext} from '../server/workflow.mjs';

const page = (access = {kind: 'none_detected'}, requirements = [], readiness = {has_rendered_text: true, document_state: 'complete', busy: false}) =>
  ({access, auth: {requirements}, readiness});

test('a 403 alone is access_denied with no cause, never a challenge or a login failure', () => {
  const reading = classifyAccess(page({kind: 'access_denied', evidence: ['http_403'], document: {status: 403}}));
  assert.equal(reading.kind, 'access_denied');
  assert.equal(reading.transient, false);
  assert.deepEqual(reading.evidence, ['http_403']);
});

test('a 403 with challenge evidence is a challenge and may still clear', () => {
  const reading = classifyAccess(page({kind: 'challenge', evidence: ['cf-mitigated: challenge'], document: {status: 403, challenge: true}}));
  assert.equal(reading.kind, 'challenge');
  assert.equal(reading.transient, true);
  assert.ok(reading.evidence.includes('http_403'));
  assert.match(settleNext('challenge'), /not established/);
});

test('loading, login, presence, limits and errors stay distinct', () => {
  assert.equal(classifyAccess(page(undefined, [], {has_rendered_text: false})).kind, 'loading');
  assert.equal(classifyAccess(page(undefined, [], {busy: true, has_rendered_text: true})).kind, 'loading');
  assert.equal(classifyAccess(page(undefined, ['password'])).kind, 'login_required');
  assert.equal(classifyAccess(page(undefined, ['passkey_or_identity_prompt'])).kind, 'presence_prompt');
  assert.equal(classifyAccess(page({kind: 'rate_limited', document: {status: 429}})).kind, 'rate_limited');
  assert.equal(classifyAccess(page({kind: 'http_error', document: {status: 503}})).kind, 'http_error');
  assert.equal(classifyAccess(page({kind: 'navigation_error', evidence: ['dns']})).kind, 'navigation_error');
  assert.equal(classifyAccess(page({kind: 'authentication_rejected'})).kind, 'authentication_rejected');
  assert.equal(classifyAccess(page(), {dialog: true}).kind, 'dialog');
});

test('no barrier never claims sign-in', () => {
  const reading = classifyAccess(page());
  assert.equal(reading.kind, 'no_barrier_detected');
  assert.match(settleNext(reading.kind), /does not prove/);
});

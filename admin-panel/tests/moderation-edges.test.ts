import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  moderationActions,
  supportedActions,
  utcExpiry,
  staffLabelBody,
  newsBody,
  reportReviewBody,
} from '../src/lib/moderation.ts';

test('every advertised action subset stays ordered, deduplicated and role gated', () => {
  for (let mask = 0; mask < 1 << moderationActions.length; mask++) {
    const expected = moderationActions.filter((_, index) => mask & (1 << index));
    const advertised = [...expected].reverse().flatMap((action) => [action, action]);
    const caps = { moderation_supported: true, moderation_actions: [...advertised, 'developer'] };
    for (const role of ['owner', 'admin', 'moderator'])
      assert.deepEqual(supportedActions(caps, role), expected);
    for (const role of ['player', 'GM', 'Owner', '', ' owner'])
      assert.deepEqual(supportedActions(caps, role), []);
  }
});

test('UTC expiry handles leap centuries, year end, maximum year and the exact boundary', () => {
  for (const text of [
    '2000-02-29T23:59',
    '2032-02-29T00:00',
    '2030-12-31T23:59',
    '9999-12-31T23:59',
  ]) {
    const milliseconds = Date.parse(text + ':00.000Z');
    assert.equal(utcExpiry(text, milliseconds - 1), milliseconds / 1000);
    assert.throws(() => utcExpiry(text, milliseconds));
    assert.throws(() => utcExpiry(text, milliseconds + 1));
  }
  for (const text of [
    '2100-02-29T00:00',
    '2030-04-31T00:00',
    '2030-01-01T24:00',
    '2030-01-01T00:60',
  ])
    assert.throws(() => utcExpiry(text, 0));
});

test('exact display, news and review limits preserve Unicode without adding authority fields', () => {
  assert.equal(staffLabelBody('é'.repeat(32), 'Boundary check').label.length, 32);
  assert.throws(() => staffLabelBody('é'.repeat(33), 'Boundary check'));
  assert.equal(newsBody('é'.repeat(1000), '', 'Boundary check').text.length, 1000);
  assert.throws(() => newsBody('é'.repeat(1001), '', 'Boundary check'));
  assert.equal(reportReviewBody('open', 'é'.repeat(512), 'Boundary check').note.length, 512);
  assert.throws(() => reportReviewBody('open', 'é'.repeat(513), 'Boundary check'));
  assert.deepEqual(Object.keys(staffLabelBody('Support', 'Boundary check')).sort(), [
    'label',
    'reason',
  ]);
});

test('all outgoing moderation text rejects embedded control categories consistently', () => {
  for (const control of ['#', '\x00', '\x7f', '\x85', '\u200b', '\u202e', '\ud800', '\ue000']) {
    const value = 'Valid' + control + 'text';
    assert.throws(() => staffLabelBody(value, 'Control check'));
    assert.throws(() => newsBody(value, '', 'Control check'));
    assert.throws(() => reportReviewBody('resolved', value, 'Control check'));
  }
});

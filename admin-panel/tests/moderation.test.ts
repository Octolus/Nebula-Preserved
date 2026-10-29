import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  moderationActions,
  supportedActions,
  moderationBody,
  maintenanceBody,
  reportReviewBody,
  canSetStaffLabel,
  staffLabelBody,
  canPublishNews,
  newsBody,
  newsIdPattern,
  canLinkOperator,
} from '../src/lib/moderation.ts';
import { allowedManagementPath } from '../src/lib/manage-policy.ts';

test('moderation controls require explicit support and recognized panel roles', () => {
  const caps = { moderation_supported: true, moderation_actions: [...moderationActions] };
  for (const role of ['owner', 'admin', 'moderator'])
    assert.deepEqual(supportedActions(caps, role), moderationActions);
  assert.deepEqual(supportedActions(caps, 'player'), []);
  assert.deepEqual(supportedActions({ moderation_actions: ['ban'] }, 'owner'), []);
  assert.deepEqual(supportedActions({ ...caps, moderation_supported: false }, 'owner'), []);
  assert.deepEqual(supportedActions({ ...caps, moderation_actions: null }, 'owner'), []);
});

test('only advertised known actions become controls; game flags do not confer panel access', () => {
  const caps = { moderation_supported: true, moderation_actions: ['kick', 'developer', 'kick'] };
  assert.deepEqual(supportedActions(caps, 'moderator'), ['kick']);
  assert.deepEqual(
    supportedActions({ ...caps, isDev: true, game_roles_supported: ['GM'] }, 'GM'),
    [],
  );
});

test('reasons are bounded and delimiter/control characters are rejected', () => {
  assert.deepEqual(moderationBody('kick', '  Verified abuse  ', ''), { reason: 'Verified abuse' });
  assert.equal(moderationBody('ban', 'x'.repeat(512), '').reason.length, 512);
  for (const reason of [
    '',
    'ab',
    'x'.repeat(513),
    'reason#field',
    'reason\nfield',
    'reason\x00field',
    'reason\x7ffield',
  ])
    assert.throws(() => moderationBody('ban', reason, ''));
});

test('ban and mute support indefinite policy or exact UTC expiry without timezone drift', () => {
  const expected = Date.UTC(2030, 5, 1, 15, 45) / 1000;
  for (const action of ['ban', 'mute'] as const) {
    assert.deepEqual(moderationBody(action, 'Verified policy', ''), {
      reason: 'Verified policy',
      expires_at: null,
    });
    assert.deepEqual(moderationBody(action, 'Verified policy', '2030-06-01T15:45', 0), {
      reason: 'Verified policy',
      expires_at: expected,
    });
    assert.deepEqual(
      moderationBody(action, 'Verified policy', '2030-06-01T15:45', 1000),
      moderationBody(action, 'Verified policy', '2030-06-01T15:45', 0),
    );
  }
});

test('invalid or elapsed dates are rejected rather than normalized to a different policy', () => {
  for (const expiry of ['2030-02-30T12:00', '2030-06-01T25:00', '2030-06-01T15:45Z', 'not-a-date'])
    assert.throws(() => moderationBody('mute', 'Verified policy', expiry, 0));
  assert.throws(() =>
    moderationBody('mute', 'Verified policy', '2030-06-01T15:45', Date.UTC(2030, 5, 1, 15, 45)),
  );
});

test('expiry is never attached to kick or policy removal commands', () => {
  for (const action of ['kick', 'unban', 'unmute'] as const)
    assert.deepEqual(moderationBody(action, 'Reviewed action', 'unused'), {
      reason: 'Reviewed action',
    });
  assert.throws(() => moderationBody('developer' as never, 'Reviewed action', ''));
});

test('proxy admits exact moderation routes while preserving existing read and mutation routes', () => {
  assert.equal(allowedManagementPath('GET', 'users/fixture-account/moderation'), true);
  for (const action of moderationActions)
    assert.equal(allowedManagementPath('POST', 'users/fixture-account/' + action), true);
  for (const path of [
    'me',
    'capabilities',
    'users',
    'audit',
    'transactions',
    'catalog',
    'operators',
    'users/1',
    'users/1/wallet',
    'users/1/owned',
    'users/1/purchases',
  ])
    assert.equal(allowedManagementPath('GET', path), true, path);
  for (const path of [
    'users/1/wallet-adjustments',
    'users/1/items',
    'users/1/rename',
    'operators/test-owner',
  ])
    assert.equal(allowedManagementPath('POST', path), true, path);
});

test('proxy denies arbitrary capabilities, wrong methods and encoded path escapes', () => {
  for (const path of [
    'users/1/developer',
    'users/1/moderation',
    'moderation/announce',
    'users/1/kick/extra',
    'users/a%2fb/kick',
    'users/1/kick?actor=owner',
    'users/1/kick#x',
    'users\\1/kick',
  ])
    assert.equal(allowedManagementPath('POST', path), false, path);
  assert.equal(allowedManagementPath('GET', 'users/1/kick'), false);
  assert.equal(allowedManagementPath('DELETE', 'users/1/ban'), false);
  assert.equal(allowedManagementPath('PUT', 'operators/test-owner'), false);
});

test('maintenance accepts bounded whole minutes including cancellation and retains the reason', () => {
  assert.deepEqual(maintenanceBody('0', 'Cancel notice'), { minutes: 0, reason: 'Cancel notice' });
  assert.deepEqual(maintenanceBody('1440', 'Planned maintenance'), {
    minutes: 1440,
    reason: 'Planned maintenance',
  });
  for (const value of ['', ' ', '-1', '1441', '0.5', 'NaN', 'Infinity'])
    assert.throws(() => maintenanceBody(value, 'Planned maintenance'));
  assert.throws(() => maintenanceBody('5', 'bad#reason'));
});

test('report review changes workflow fields only and preserves a separate bounded note', () => {
  for (const status of ['open', 'resolved', 'dismissed'])
    assert.deepEqual(reportReviewBody(status, ' Reviewed report ', 'Review complete'), {
      status,
      note: 'Reviewed report',
      reason: 'Review complete',
    });
  assert.equal(reportReviewBody('open', '', 'New review').note, '');
  assert.throws(() => reportReviewBody('banned', '', 'Invalid status'));
  assert.throws(() => reportReviewBody('open', 'x'.repeat(513), 'Long note'));
  assert.deepEqual(Object.keys(reportReviewBody('resolved', 'Note', 'Review complete')).sort(), [
    'note',
    'reason',
    'status',
  ]);
});

test('proxy permits exact report and maintenance operations without broadening arbitrary paths', () => {
  for (const path of ['moderation/status', 'moderation/events', 'moderation/reports'])
    assert.equal(allowedManagementPath('GET', path), true, path);
  assert.equal(allowedManagementPath('POST', 'moderation/maintenance'), true);
  assert.equal(allowedManagementPath('POST', 'moderation/reports/' + 'a'.repeat(64)), true);
  for (const path of [
    'moderation/reports/' + 'a'.repeat(63),
    'moderation/reports/' + 'z'.repeat(64),
    'moderation/reports/' + 'a'.repeat(64) + '/ban',
    'moderation/maintenance\n',
    'users/1/kick\r',
  ])
    assert.equal(allowedManagementPath('POST', path), false, path);
  assert.equal(allowedManagementPath('GET', 'moderation/maintenance'), false);
  assert.equal(allowedManagementPath('POST', 'moderation/events'), false);
});

test('wire fields reject Unicode controls and report notes cannot inject delimiters', () => {
  for (const character of ['\u200b', '\u202e', '\ud800', '\ue000', '#']) {
    assert.throws(() => moderationBody('ban', 'Reason' + character, ''));
    assert.throws(() => reportReviewBody('open', 'Note' + character, 'Review reason'));
  }
  assert.throws(() => reportReviewBody('open', 'Two\nlines', 'Review reason'));
  assert.equal(moderationBody('kick', 'Review café 😀', '').reason, 'Review café 😀');
});

test('staff labels require owner capability and remain display text without permission fields', () => {
  for (const role of ['admin', 'moderator', 'GM', ''])
    assert.equal(canSetStaffLabel({ staff_labels_supported: true }, role), false);
  assert.equal(canSetStaffLabel({ staff_labels_supported: true }, 'owner'), true);
  assert.equal(canSetStaffLabel({}, 'owner'), false);
  assert.deepEqual(staffLabelBody('', 'Clear display label'), {
    label: '',
    reason: 'Clear display label',
  });
  assert.equal(
    staffLabelBody('Support / Volunteer', 'Set display label').label,
    'Support / Volunteer',
  );
  for (const value of ['x'.repeat(33), '<owner>', 'Label#x', 'Label\u200b'])
    assert.throws(() => staffLabelBody(value, 'Set display label'));
  assert.deepEqual(Object.keys(staffLabelBody('Helper', 'Set display label')).sort(), [
    'label',
    'reason',
  ]);
});

test('news publishing requires an advertised capability and admin or owner role', () => {
  for (const role of ['owner', 'admin'])
    assert.equal(canPublishNews({ news_supported: true }, role), true);
  for (const role of ['moderator', 'GM', ''])
    assert.equal(canPublishNews({ news_supported: true }, role), false);
  assert.equal(canPublishNews({ announcement_supported: true }, 'owner'), false);
});

test('news body is bounded wire text with stable UTC expiry and no invented date or broadcast fields', () => {
  assert.deepEqual(newsBody(' Welcome players ', '', 'Publish news'), {
    text: 'Welcome players',
    expires_at: null,
    reason: 'Publish news',
  });
  assert.equal(
    newsBody('x'.repeat(1000), '2030-06-01T15:45', 'Publish news', 0).expires_at,
    Date.UTC(2030, 5, 1, 15, 45) / 1000,
  );
  for (const text of ['', 'x'.repeat(1001), 'Hello#world', 'Hello\nworld', 'Hello\u202eworld'])
    assert.throws(() => newsBody(text, '', 'Publish news'));
  assert.throws(() => newsBody('News', '2030-02-30T00:00', 'Publish news', 0));
  assert.deepEqual(Object.keys(newsBody('News', '', 'Publish news')).sort(), [
    'expires_at',
    'reason',
    'text',
  ]);
});

test('news routes use exact canonical UUIDs and staff display has its own explicit route', () => {
  const id = '01234567-89ab-cdef-0123-456789abcdef';
  assert.equal(newsIdPattern.test(id), true);
  assert.equal(allowedManagementPath('GET', 'moderation/news'), true);
  assert.equal(allowedManagementPath('POST', 'moderation/news'), true);
  assert.equal(allowedManagementPath('POST', 'moderation/news/' + id + '/archive'), true);
  assert.equal(allowedManagementPath('POST', 'users/1/staff-label'), true);
  for (const value of [id.toUpperCase(), id.replaceAll('-', ''), 'not-a-news-id', id + '/delete'])
    assert.equal(
      allowedManagementPath('POST', 'moderation/news/' + value + '/archive'),
      false,
      value,
    );
  for (const path of ['users/1/role', 'users/1/isDev', 'moderation/announcement'])
    assert.equal(allowedManagementPath('POST', path), false, path);
});

test('operator player links require an explicit owner capability and an exact dedicated route', () => {
  assert.equal(canLinkOperator({ operator_account_links_supported: true }, 'owner'), true);
  for (const role of ['admin', 'moderator', 'player'])
    assert.equal(canLinkOperator({ operator_account_links_supported: true }, role), false);
  assert.equal(canLinkOperator({}, 'owner'), false);
  assert.equal(allowedManagementPath('POST', 'operators/independent-operator/player-link'), true);
  assert.equal(allowedManagementPath('GET', 'operators/independent-operator/player-link'), false);
  assert.equal(
    allowedManagementPath('POST', 'operators/independent-operator/player-link/extra'),
    false,
  );
});

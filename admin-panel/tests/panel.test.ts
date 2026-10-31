import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  panelRoute,
  playerHref,
  playerReference,
  formatCell,
  playerTabs,
} from '../src/lib/panel.ts';
import { allowedManagementPath } from '../src/lib/manage-policy.ts';
test('player links preserve identity and tab through browser reload and history', () => {
  for (const id of ['player-one', 'space name', 'player#one', 'é玩家', '100%'])
    for (const tab of playerTabs)
      assert.deepEqual(panelRoute(playerHref(id, tab)), { view: 'users', id, tab });
});
test('malformed and unsupported routes never select another account or API path', () => {
  for (const hash of [
    '#users/%',
    '#users/one/unknown',
    '#users/%2fadmin',
    '#users/%00',
    '#users/x/credits/extra',
    '#operators/name',
  ])
    assert.equal(panelRoute(hash).id, '');
  assert.deepEqual(panelRoute(''), { view: 'overview', id: '', tab: 'summary' });
});
test('player references distinguish operators and report targets from player accounts', () => {
  assert.equal(playerReference('account_id', { account_id: 'player' }), 'player');
  assert.equal(
    playerReference('reporter_account_id', { reporter_account_id: 'reporter' }),
    'reporter',
  );
  for (const operation of [
    'wallet.adjust',
    'items.grant',
    'users.rename',
    'moderation.ban',
    'players.staff',
  ])
    assert.equal(playerReference('target_id', { operation, target_id: 'player' }), 'player');
  for (const operation of [
    'operators.manage',
    'operators.bootstrap',
    'moderation.reports',
    'moderation.news',
    'moderation.maintenance',
  ])
    assert.equal(playerReference('target_id', { operation, target_id: 'not-a-player' }), null);
  assert.equal(playerReference('target', { target: 'unverified-username' }), null);
});
test('account history routes are read-only and reject path injection', () => {
  for (const suffix of ['transactions', 'audit']) {
    assert.equal(allowedManagementPath('GET', 'users/player/' + suffix), true);
    assert.equal(allowedManagementPath('POST', 'users/player/' + suffix), false);
    for (const id of ['%2f', 'a\\b', 'x?y', 'x#y', 'x\n'])
      assert.equal(allowedManagementPath('GET', 'users/' + id + '/' + suffix), false);
  }
});
test('missing timestamps and malformed dates are not displayed as recent logins', () => {
  for (const value of [null, undefined]) assert.equal(formatCell('last_login_at', value), '—');
  assert.equal(formatCell('last_login_at', Infinity), '—');
  assert.equal(formatCell('online', 0), 'Offline');
  assert.equal(formatCell('online', 1), 'Online');
  assert.equal(formatCell('enabled', 1), 'Enabled');
  assert.equal(formatCell('enabled', 0), 'Disabled');
  assert.equal(formatCell('currency', 'np'), 'Nebula Points');
  assert.equal(formatCell('source', 'admin'), 'Operator grant');
});
test('staff action routes are allowed exactly and reject injection', () => {
  for (const path of [
    'users/p1/move',
    'users/p1/clear-profile',
    'moderation/server-status',
    'moderation/disconnect-all',
    'moderation/instances/inst-1/evacuate',
    'users/p1/character/housing/grant',
    'users/p1/character/housing/remove',
  ])
    assert.equal(allowedManagementPath('POST', path), true, path);
  for (const path of [
    'users/p1/live',
    'moderation/scenes',
    'moderation/instances',
    'moderation/server-status',
    'feed',
    'monitor',
    'purchases',
    'users/p1/character/housing-options',
  ])
    assert.equal(allowedManagementPath('GET', path), true, path);
  for (const path of [
    'moderation/instances/../evacuate',
    'moderation/instances/a/b/evacuate',
    'users/p1/move/x',
    'users/%2f/move',
    'moderation/disconnect-all?x=1',
  ])
    assert.equal(allowedManagementPath('POST', path), false, path);
  assert.equal(allowedManagementPath('GET', 'users/p1/move'), false);
});

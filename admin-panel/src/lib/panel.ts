export type Row = Record<string, unknown>;
export const playerTabs = [
  'summary',
  'character',
  'inventory',
  'purchases',
  'credits',
  'sessions',
  'moderation',
  'activity',
] as const;
export type PlayerTab = (typeof playerTabs)[number];
const views = [
  'overview',
  'monitor',
  'users',
  'moderation',
  'purchases',
  'transactions',
  'catalog',
  'stores',
  'audit',
  'operators',
];
export function playerHref(id: string, tab: PlayerTab = 'summary') {
  return '#users/' + encodeURIComponent(id) + '/' + tab;
}
export function panelRoute(hash: string) {
  try {
    const [view, encoded, tab, extra] = hash.replace(/^#/, '').split('/');
    if (!views.includes(view) || extra !== undefined)
      return { view: 'overview', id: '', tab: 'summary' as PlayerTab };
    if (encoded !== undefined) {
      const id = decodeURIComponent(encoded);
      if (
        view === 'stores' &&
        id &&
        id.length <= 128 &&
        !/[\\/\x00-\x1f\x7f]/.test(id) &&
        tab === undefined
      )
        return { view, id, tab: 'summary' as PlayerTab };
      if (
        view !== 'users' ||
        !id ||
        id.length > 128 ||
        /[\\/\x00-\x1f\x7f]/.test(id) ||
        (tab !== undefined && !playerTabs.includes(tab as PlayerTab))
      )
        return { view: 'users', id: '', tab: 'summary' as PlayerTab };
      return { view, id, tab: (tab || 'summary') as PlayerTab };
    }
    return { view, id: '', tab: 'summary' as PlayerTab };
  } catch {
    return { view: 'users', id: '', tab: 'summary' as PlayerTab };
  }
}
export function display(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : 'None';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
export function formatCell(key: string, value: unknown) {
  if (key === 'enabled') return value === true || value === 1 ? 'Enabled' : 'Disabled';
  if (key === 'currency' && value === 'np') return 'Nebula Points';
  if (key === 'source')
    return (
      ({ buy: 'Store purchase', gift: 'Gift', admin: 'Operator grant' } as Record<string, string>)[
        String(value)
      ] || display(value)
    );
  if (key === 'online') return value === true || value === 1 ? 'Online' : 'Offline';
  if (key === 'operation') return operationLabel(value);
  if (key === 'result')
    return value === 'success' ? 'Success' : value === 'failure' ? 'Failed' : display(value);
  if (key === 'end_reason' && typeof value === 'string')
    return (
      (
        {
          replaced: 'New login',
          timeout: 'Timed out',
          kicked: 'Kicked',
          banned: 'Banned',
          revoked: 'Revoked',
        } as Record<string, string>
      )[value] || value.replace('gateway_close:', 'Disconnected: ')
    );
  if (key === 'delta' && typeof value === 'number')
    return (value > 0 ? '+' : '') + value.toLocaleString();
  if (key === 'role' && typeof value === 'string') return value[0].toUpperCase() + value.slice(1);
  if (key === 'duration_seconds' && typeof value === 'number') return duration(value);
  if ((key.endsWith('_at') || key === 'last_login_at') && typeof value === 'number') {
    const date = new Date(value * 1000);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : '—';
  }
  if (typeof value === 'number') return value.toLocaleString();
  return display(value);
}
export const labels: Record<string, string> = {
  enabled: 'Access',
  account_id: 'Player',
  username: 'Username',
  np: 'Nebula Points',
  crystals: 'Crystals',
  last_login_at: 'Last login',
  last_avatar_save_at: 'Last avatar save',
  created_at: 'When',
  operation: 'Action',
  reason: 'Note',
  store_name: 'Store',
  name: 'Item',
  source: 'How',
  actor_role: 'Role',
  last_actor_id: 'By',
  granted_by: 'By',
  duration_seconds: 'Duration',
  ip: 'IP address',
  geo: 'Location',
  result: 'Result',
  started_at: 'Started',
  ended_at: 'Ended',
  end_reason: 'Ended by',
  first_seen: 'First seen',
  last_seen: 'Last seen',
  login_count: 'Logins',
  other_accounts: 'Other players on this IP',
  world: 'World',
  players: 'Players',
  process_state: 'State',
  owner_account_id: 'Owner',
  waiting_seconds: 'Waiting',
  event: 'Event',
  route: 'Request',
  message: 'Details',
  timestamp: 'When',
  memory: 'Memory',
  client_version: 'Game build',
  prop_use_count: 'Uses',
  units: 'Units',
  label: 'Name',
  until: 'Until',
  subcategory: 'Sub-category',
  store_category_label: 'Shop category',
  shop_path: 'In-game shop path',
  shop_reachable: 'Reachable in game shop',
  gender_variant: 'Character variant',
  slot_side: 'Side',
  housing_group: 'Furniture group',
  variant_family_size: 'Colour/style variants',
  season_hint: 'Season',
  also_in_categories: 'Also listed in',
  last_action_at: 'Last action',
  option: 'Category',
  text: 'Message',
  status: 'Status',
  granted_at: 'Granted',
  item_id: 'Item ID',
  offer_id: 'Offer ID',
  display_name: 'Item',
  target_id: 'Target',
  actor_id: 'By',
  delta: 'Change',
  before_balance: 'Before',
  after_balance: 'Balance after',
  reporter_account_id: 'Reporter',
  current_offer_crystals: 'Current crystal price',
  current_offer_np: 'Current points price',
  historical_price_known: 'Original price retained',
  category_label: 'Category',
  category_id: 'Category ID',
  collection: 'Collection',
  resource_path: 'Game resource path',
  thumbnail_path: 'Game thumbnail reference',
  asset_path: 'Shipped asset path',
  manifest_sha256: 'Manifest SHA-256',
  availability: 'Store availability',
  display_name_source: 'Display name source',
  bundle_size: 'Bundle size (bytes)',
  dependencies: 'Bundle dependencies',
  category_evidence: 'Category evidence',
  store_category: 'In-game store category',
  store_category_source: 'Store category source',
  thumbnail_source: 'Thumbnail source',
  own_thumbnail_known: 'Own thumbnail identified',
};
export const fieldLabel = (key: string) => labels[key] || key.replaceAll('_', ' ');
export function playerReference(key: string, row: Row): string | null {
  const value = row[key];
  if (typeof value !== 'string' || !value) return null;
  if (key === 'account_id' || key === 'reporter_account_id') return value;
  // Operator/news/report targets are not player identities.
  if (
    key === 'target_id' &&
    /^(?:wallet\.|items\.|users\.|players\.staff|moderation\.(?:ban|unban|kick|mute|unmute|staff))/.test(
      String(row.operation),
    )
  )
    return value;
  return null;
}

const operations: Record<string, string> = {
  'wallet.adjust': 'Credits adjusted',
  'items.grant': 'Item given',
  'users.rename': 'Player renamed',
  'catalog.manage': 'Store updated',
  'players.data': 'Save data edited',
  'players.staff': 'Staff label set',
  'operators.manage': 'Panel access changed',
  'operators.bootstrap': 'Panel owner created',
  'moderation.ban': 'Banned',
  'moderation.unban': 'Unbanned',
  'moderation.kick': 'Kicked',
  'moderation.mute': 'Muted',
  'moderation.unmute': 'Unmuted',
  'moderation.reports': 'Report reviewed',
  'report.review': 'Report reviewed',
  'moderation.news': 'Login news changed',
  'moderation.maintenance': 'Maintenance notice changed',
};
export function operationLabel(value: unknown) {
  const key = String(value ?? '');
  return operations[key] || key.replace(/[._]/g, ' ').replace(/^./, (c) => c.toUpperCase()) || '—';
}
export function duration(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return Math.round(seconds) + 's';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + 'm';
  const hours = Math.floor(minutes / 60);
  return hours < 48
    ? hours + 'h ' + (minutes % 60) + 'm'
    : Math.floor(hours / 24) + 'd ' + (hours % 24) + 'h';
}
export function relative(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const seconds = Date.now() / 1000 - value;
  if (seconds < 0) return new Date(value * 1000).toLocaleString();
  if (seconds < 60) return 'just now';
  return duration(seconds) + ' ago';
}
export function shortId(value: unknown) {
  const text = String(value ?? '');
  return text.length > 14 ? text.slice(0, 6) + '…' + text.slice(-4) : text;
}
/** Readable name + link for an ID-bearing column; IDs stay as secondary text. */
export function entity(
  key: string,
  row: Row,
): { label: string; href?: string; id?: string } | null {
  const value = row[key];
  if (typeof value !== 'string' || !value) return null;
  const player = playerReference(key, row);
  const named = (name: unknown) => (typeof name === 'string' && name.trim() ? name : null);
  if (key === 'account_id')
    return {
      label: named(row.account_name) || named(row.username) || shortId(value),
      href: playerHref(value),
      id: value,
    };
  if (key === 'reporter_account_id')
    return {
      label: named(row.reporter_name) || shortId(value),
      href: playerHref(value),
      id: value,
    };
  if (key === 'target_id') {
    const type = row.target_type;
    const label = named(row.target_name);
    if (type === 'player' || player)
      return { label: label || shortId(value), href: playerHref(value), id: value };
    if (type === 'store')
      return {
        label: label || shortId(value),
        href: '#stores/' + encodeURIComponent(value),
        id: value,
      };
    if (type === 'listing') return { label: label || shortId(value), id: value };
    if (type === 'operator') return { label: value, href: '#operators' };
    if (type === 'report') return { label: 'Player report', id: value };
    if (type === 'news') return { label: 'Login news', id: value };
    if (type === 'server' || value === 'server') return { label: label || 'Server' };
    return { label: label || shortId(value), id: value };
  }
  if (key === 'actor_id' || key === 'last_actor_id' || key === 'granted_by')
    return { label: value };
  if (key === 'target' && typeof row.target_account_id === 'string')
    return { label: value, href: playerHref(row.target_account_id), id: row.target_account_id };
  return null;
}

// Mirrors backend NONMINI_PUBLIC_SCENES (shared worlds; everything else is a personal space).
const publicScenes = new Set([
  'Nexus',
  'LeafPark',
  'Beach',
  'Cinema',
  'Bowling',
  'Dome',
  'StoneLakeCastle',
  'Cube',
  'GhostTown',
  'TheNebulianOpenHouse',
  'ZeroDistrict',
  'NebuHouseOpenHouse',
  'WestValleyApartmentOpenHouse',
  'MedievalVillage',
  'SKL',
]);
/** "CampSilverLake" -> "Camp Silver Lake"; trailing variant digits dropped. */
export function sceneLabel(value: unknown) {
  const raw = String(value ?? '').trim();
  if (!raw) return 'Menus / loading';
  return raw
    .replace(/[0-9]+$/, '')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replaceAll('_', ' ');
}
export function isPublicScene(value: unknown) {
  return publicScenes.has(String(value ?? ''));
}

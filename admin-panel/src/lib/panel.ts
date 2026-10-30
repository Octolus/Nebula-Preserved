export type Row = Record<string, unknown>;
export const playerTabs = [
  'summary',
  'inventory',
  'purchases',
  'credits',
  'moderation',
  'activity',
] as const;
export type PlayerTab = (typeof playerTabs)[number];
const views = ['overview', 'users', 'moderation', 'transactions', 'catalog', 'audit', 'operators'];
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
  if ((key.endsWith('_at') || key === 'last_login_at') && typeof value === 'number') {
    const date = new Date(value * 1000);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : '—';
  }
  return display(value);
}
export const labels: Record<string, string> = {
  enabled: 'Access',
  account_id: 'Player',
  username: 'Username',
  np: 'Nebula Points',
  last_login_at: 'Last login',
  last_avatar_save_at: 'Last avatar save',
  created_at: 'Created',
  granted_at: 'Granted',
  item_id: 'Item ID',
  offer_id: 'Offer ID',
  display_name: 'Item',
  target_id: 'Target',
  actor_id: 'Operator',
  delta: 'Change',
  before_balance: 'Before',
  after_balance: 'After',
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

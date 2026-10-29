export const moderationActions = ['ban', 'unban', 'kick', 'mute', 'unmute'] as const;
export type ModerationAction = (typeof moderationActions)[number];
export const actionLabels: Record<ModerationAction, string> = {
  ban: 'Ban player',
  unban: 'Unban player',
  kick: 'Kick player',
  mute: 'Mute player',
  unmute: 'Unmute player',
};

export function supportedActions(capabilities: Record<string, unknown>, role: string) {
  const reported = capabilities.moderation_actions;
  if (
    capabilities.moderation_supported !== true ||
    !['owner', 'admin', 'moderator'].includes(role) ||
    !Array.isArray(reported)
  )
    return [];
  return moderationActions.filter((action) => reported.includes(action));
}

export function moderationBody(
  action: ModerationAction,
  reason: string,
  expiry: string,
  now = Date.now(),
) {
  if (!moderationActions.includes(action)) throw new Error('Unsupported moderation action');
  const body: { reason: string; expires_at?: number | null } = { reason: moderationReason(reason) };
  if (action === 'ban' || action === 'mute') {
    body.expires_at = null;
    if (expiry) {
      body.expires_at = utcExpiry(expiry, now);
    }
  }
  return body;
}

export function moderationReason(reason: string) {
  const text = reason.trim();
  if (text.length < 3 || text.length > 512 || /[#\p{C}]/u.test(text))
    throw new Error('Use a reason of 3–512 characters without # or control characters.');
  return text;
}

export function maintenanceBody(minutes: string, reason: string) {
  const value = Number(minutes);
  if (!minutes.trim() || !Number.isSafeInteger(value) || value < 0 || value > 1440)
    throw new Error('Maintenance minutes must be a whole number from 0 to 1440.');
  return { minutes: value, reason: moderationReason(reason) };
}

export function reportReviewBody(status: string, note: string, reason: string) {
  if (!['open', 'resolved', 'dismissed'].includes(status))
    throw new Error('Choose a valid report status.');
  if (note.length > 512 || /[#\p{C}]/u.test(note))
    throw new Error('Use a note of at most 512 characters without # or control characters.');
  return { status, note: note.trim(), reason: moderationReason(reason) };
}

export function utcExpiry(expiry: string, now = Date.now()) {
  if (!expiry) return null;
  const milliseconds = Date.parse(expiry + ':00.000Z');
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(expiry) ||
    !Number.isFinite(milliseconds) ||
    new Date(milliseconds).toISOString().slice(0, 16) !== expiry ||
    milliseconds <= now
  )
    throw new Error('Choose a valid future expiry in UTC, or leave it empty.');
  return milliseconds / 1000;
}

export function canSetStaffLabel(capabilities: Record<string, unknown>, role: string) {
  return role === 'owner' && capabilities.staff_labels_supported === true;
}

export function staffLabelBody(label: string, reason: string) {
  const value = label.trim();
  if (value.length > 32 || /[<>#\p{C}]/u.test(value))
    throw new Error(
      'Use a plain display label of at most 32 characters without <, >, # or control characters.',
    );
  return { label: value, reason: moderationReason(reason) };
}

export function canPublishNews(capabilities: Record<string, unknown>, role: string) {
  return ['owner', 'admin'].includes(role) && capabilities.news_supported === true;
}

export function newsBody(text: string, expiry: string, reason: string, now = Date.now()) {
  const value = text.trim();
  if (!value || value.length > 1000 || /[#\p{C}]/u.test(value))
    throw new Error(
      'Use one paragraph of at most 1000 characters without # or control characters.',
    );
  return { text: value, expires_at: utcExpiry(expiry, now), reason: moderationReason(reason) };
}

export const newsIdPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

export function canLinkOperator(capabilities: Record<string, unknown>, role: string) {
  return role === 'owner' && capabilities.operator_account_links_supported === true;
}

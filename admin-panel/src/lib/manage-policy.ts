const reads =
  /^(?:me|capabilities|stats|health|users|audit|transactions|catalog|operators|moderation\/(?:status|events|reports|news)|users\/[^/]+(?:\/(?:wallet|owned|purchases|moderation|transactions|audit))?)$/;
const writes =
  /^(?:users\/[^/]+\/(?:wallet-adjustments|items|rename|ban|unban|kick|mute|unmute|staff-label)|operators\/[^/]+(?:\/player-link)?|moderation\/(?:maintenance|reports\/[a-f0-9]{64}|news|news\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/archive))$/;

export function allowedManagementPath(method: string, path: string) {
  return (
    ['GET', 'POST'].includes(method) &&
    (method === 'GET' ? reads : writes).test(path) &&
    !/[\\%?#\x00-\x1f\x7f]/.test(path)
  );
}

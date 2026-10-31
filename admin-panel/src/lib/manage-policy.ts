const reads =
  /^(?:me|capabilities|stats|health|feed|users|audit|transactions|purchases|catalog|operators|stores|monitor|monitor\/logins|monitor\/ips\/[0-9a-fA-F.:]{2,45}|stores\/[^/]+|store-offers\/[^/]+|moderation\/(?:status|events|reports|news|active|scenes|instances|server-status)|users\/[^/]+(?:\/(?:wallet|owned|purchases|moderation|transactions|audit|sessions|logins|ips|live|character(?:\/[^/]+){0,3}))?)$/;
const writes =
  /^(?:users\/[^/]+\/(?:wallet-adjustments|items|rename|ban|unban|kick|mute|unmute|staff-label|move|clear-profile|character(?:\/[^/]+){1,3})|stores\/[^/]+|store-offers\/[^/]+|operators\/[^/]+(?:\/player-link)?|moderation\/(?:maintenance|server-status|disconnect-all|instances\/[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\/evacuate|reports\/[a-f0-9]{64}|news|news\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/archive))$/;

export function allowedManagementPath(method: string, path: string) {
  return (
    ['GET', 'POST'].includes(method) &&
    (method === 'GET' ? reads : writes).test(path) &&
    !/[\\%?#\x00-\x1f\x7f]/.test(path)
  );
}

export function managementQuery(path: string, parameters: URLSearchParams) {
  const query = new URLSearchParams();
  const allowed = [
    'limit',
    'cursor',
    'q',
    'account_id',
    'actor',
    'operation',
    'kind',
    'category',
    'status',
    'result',
    'since',
    'direction',
    'raw',
  ];
  if (path === 'catalog') allowed.push('gender', 'store_id');
  else if (/^users\/[^/]+\/character\//.test(path)) allowed.push('gender');
  for (const key of allowed) {
    const value = parameters.get(key);
    if (value !== null) query.set(key, value.slice(0, 256));
  }
  return query;
}

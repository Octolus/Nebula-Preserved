import { Badge } from './ui/badge';
import { PaginatedRecords } from './management-widgets';
import { duration, playerHref, relative, type Row } from '../lib/panel';

type Api = (path: string) => Promise<any>;

export function GeoText({ geo, status }: { geo: unknown; status?: unknown }) {
  const g = (geo && typeof geo === 'object' ? geo : {}) as Row;
  const place = [g.city, g.region, g.country].filter(Boolean).join(', ');
  if (!place)
    return (
      <span className="text-xs text-muted-foreground">
        {(
          {
            private: 'Local network',
            pending: 'Looking up…',
            disabled: 'Lookup off',
            unavailable: 'Lookup failed',
          } as Record<string, string>
        )[String(status)] || 'Unknown'}
      </span>
    );
  return (
    <span className="inline-flex flex-col text-xs">
      <span>{place}</span>
      {g.isp ? <span className="text-muted-foreground">{String(g.isp)}</span> : null}
    </span>
  );
}

/** Login sessions, IP addresses and locations for one player. */
export function SessionsPanel({
  accountId,
  api,
  revision,
}: {
  accountId: string;
  api: Api;
  revision: number;
}) {
  const base = 'users/' + encodeURIComponent(accountId);
  return (
    <div className="grid gap-3">
      <PaginatedRecords
        title="Sessions"
        path={base + '/sessions'}
        revision={revision}
        load={api}
        description="Each time the player opened the game. Live sessions are still running."
        columns={['started_at', 'duration_seconds', 'ip', 'geo', 'client_version', 'end_reason']}
        render={{
          started_at: (row) => (
            <span className="inline-flex flex-col">
              <span>{new Date(Number(row.started_at) * 1000).toLocaleString()}</span>
              <span className="text-xs text-muted-foreground">{relative(row.started_at)}</span>
            </span>
          ),
          duration_seconds: (row) => (
            <span className="flex items-center gap-1">
              {row.live === true && <Badge>Live</Badge>}
              {typeof row.duration_seconds === 'number' ? duration(row.duration_seconds) : '—'}
            </span>
          ),
          ip: (row) => <span className="font-mono text-xs">{String(row.ip || '—')}</span>,
          geo: (row) => <GeoText geo={row.geo} status={row.geo_status} />,
          end_reason: (row) =>
            row.live === true ? (
              <span className="text-muted-foreground">—</span>
            ) : (
              <EndReason row={row} />
            ),
        }}
        emptyText="No sessions recorded yet. Sessions are recorded from now on."
      />
      <PaginatedRecords
        title="IP addresses"
        path={base + '/ips'}
        revision={revision}
        load={api}
        description="Where this player connects from, and other players seen on the same address."
        columns={['ip', 'geo', 'login_count', 'last_seen', 'other_accounts']}
        render={{
          ip: (row) => <span className="font-mono text-xs">{String(row.ip)}</span>,
          geo: (row) => <GeoText geo={row.geo} status={row.geo_status} />,
          last_seen: (row) => relative(row.last_seen),
          other_accounts: (row) => {
            const others = Array.isArray(row.other_accounts) ? (row.other_accounts as Row[]) : [];
            return others.length ? (
              <span className="flex flex-wrap gap-1">
                {others.map((other) => (
                  <a key={String(other.account_id)} href={playerHref(String(other.account_id))}>
                    <Badge variant="secondary">
                      {String(other.account_name || other.account_id)}
                    </Badge>
                  </a>
                ))}
              </span>
            ) : (
              <span className="text-muted-foreground">None</span>
            );
          },
        }}
        emptyText="No IP addresses recorded yet."
      />
      <PaginatedRecords
        title="Failed logins"
        path={base + '/logins'}
        revision={revision}
        load={api}
        params={{ result: 'failure' }}
        columns={['created_at', 'reason', 'ip', 'geo']}
        render={{ geo: (row) => <GeoText geo={row.geo} status={row.geo_status} /> }}
        emptyText="No failed logins."
      />
    </div>
  );
}

function EndReason({ row }: { row: Row }) {
  const value = String(row.end_reason || '');
  const label =
    (
      {
        replaced: 'New login',
        timeout: 'Timed out',
        kicked: 'Kicked',
        banned: 'Banned',
        revoked: 'Revoked',
      } as Record<string, string>
    )[value] ||
    (
      {
        stream_eof: 'Closed the game',
        timeout: 'Connection lost',
        transport_error: 'Network error',
        cancelled: 'Server restart',
      } as Record<string, string>
    )[value.replace('gateway_close:', '')] ||
    (value
      ? 'Disconnected (' + value.replace('gateway_close:', '').replaceAll('_', ' ') + ')'
      : '—');
  return <span>{label}</span>;
}

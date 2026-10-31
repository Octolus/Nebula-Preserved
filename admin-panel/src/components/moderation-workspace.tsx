import { RecordList } from './record-list';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { FormSelect } from './form-select';
import { Textarea } from './ui/textarea';
import { Checkbox } from './ui/checkbox';
import { useCallback, useEffect, useState } from 'react';
import { ModerationPanel } from './moderation-panel';
import { NewsPanel } from './news-panel';
import { maintenanceBody, reportReviewBody } from '../lib/moderation';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import { PaginatedRecords } from './management-widgets';
import { playerHref } from '../lib/panel';
import { AdminActions, UnsupportedActions } from './admin-actions';

type Data = Record<string, unknown>;
type Api = <T = Data>(path: string, body?: Data) => Promise<T>;
type List = { items: Data[]; total: number; next_cursor: string | null };
const empty: List = { items: [], total: 0, next_cursor: null };
const display = (value: unknown) =>
  value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const receipt = (result: Data) =>
  `Change committed. Audit record ${result.audit_id ?? result.request_id}.`;

function Maintenance({
  actor,
  api,
  revision,
  onCommitted,
}: {
  actor: { role: string };
  api: Api;
  revision: number;
  onCommitted: () => void;
}) {
  const [status, setStatus] = useState<Data | null>(null);
  const [minutes, setMinutes] = useState('0');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    api('moderation/status')
      .then((value) => {
        if (current) setStatus(value);
      })
      .catch((failure) => {
        if (current) setError(failure.message);
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [api, revision, refresh]);
  async function submit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || busy || !confirmed || !['admin', 'owner'].includes(actor.role)) return;
    setError('');
    setNotice('');
    try {
      const body = maintenanceBody(minutes, reason);
      setSaving(true);
      const result = await api('moderation/maintenance', body);
      setNotice(
        receipt(result) +
          ' Game clients poll for maintenance notices; client display is not acknowledged here.',
      );
      setConfirmed(false);
      setReason('');
      setRefresh((value) => value + 1);
      onCommitted();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Maintenance notice</CardTitle>
        <CardDescription>
          Publish the server's maintenance minutes. Zero clears the notice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {busy && <p role="status">Loading server notice…</p>}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="rounded-md border p-3 text-sm">
            {notice}
          </p>
        )}
        {!busy && status && (
          <p className="text-sm">
            Reported maintenance notice:{' '}
            <strong>{display(status.maintenance_minutes)} minutes</strong>
          </p>
        )}
        {['admin', 'owner'].includes(actor.role) && status && (
          <form onSubmit={submit} className="space-y-4 border-t pt-4">
            <div className="space-y-2">
              <Label htmlFor="maintenance-minutes">Maintenance minutes</Label>
              <Input
                id="maintenance-minutes"
                type="number"
                min={0}
                max={1440}
                step={1}
                required
                value={minutes}
                disabled={saving}
                onChange={(event) => {
                  setMinutes(event.target.value);
                  setConfirmed(false);
                }}
                className="min-h-9"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="maintenance-reason">Maintenance reason</Label>
              <Input
                id="maintenance-reason"
                required
                minLength={3}
                maxLength={512}
                value={reason}
                disabled={saving}
                onChange={(event) => {
                  setReason(event.target.value);
                  setConfirmed(false);
                }}
                className="min-h-9"
              />
            </div>
            <label className="flex min-h-9 items-center gap-3 text-sm">
              <Checkbox
                required
                checked={confirmed}
                disabled={saving}
                onCheckedChange={(checked) => setConfirmed(checked === true)}
              />
              I checked the maintenance notice for this server.
            </label>
            <Button className="min-h-9" disabled={busy || saving || !confirmed}>
              {saving ? 'Committing…' : 'Set maintenance notice'}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function ReportReview({
  report,
  api,
  close,
  committed,
}: {
  report: Data;
  api: Api;
  close: () => void;
  committed: () => void;
}) {
  const [status, setStatus] = useState(display(report.status));
  const [note, setNote] = useState(typeof report.note === 'string' ? report.note : '');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function submit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !confirmed || !/^[a-f0-9]{64}$/.test(String(report.report_id))) return;
    setError('');
    setNotice('');
    try {
      const body = reportReviewBody(status, note, reason);
      setSaving(true);
      const result = await api('moderation/reports/' + report.report_id, body);
      setNotice(receipt(result));
      setConfirmed(false);
      setReason('');
      committed();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4 rounded-md border p-4">
      <h3 className="font-semibold">Review report</h3>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">Reported player</dt>
          <dd className="break-words">
            {typeof report.target_account_id === 'string' ? (
              <a
                className="underline-offset-4 hover:underline"
                href={playerHref(report.target_account_id, 'moderation')}
              >
                {display(report.target)}
              </a>
            ) : (
              display(report.target) + ' (no matching account)'
            )}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Reported by</dt>
          <dd className="break-all">
            <a
              className="underline-offset-4 hover:underline"
              href={playerHref(String(report.reporter_account_id))}
            >
              {display(report.reporter_name || report.reporter_account_id)}
            </a>
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground">Report text</dt>
          <dd className="break-words whitespace-pre-wrap">{display(report.text)}</dd>
        </div>
      </dl>
      <p className="text-xs text-muted-foreground">
        Reviewing a report only changes its status. To act on the player, open their Moderation tab.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md border p-3 text-sm">
          {notice}
        </p>
      )}
      <div className="space-y-2">
        <Label htmlFor="report-status">Report status</Label>
        <FormSelect
          id="report-status"
          value={status}
          disabled={saving}
          options={['open', 'resolved', 'dismissed']}
          onValueChange={(value) => {
            setStatus(value);
            setConfirmed(false);
          }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="report-note">Operator note (optional)</Label>
        <Textarea
          id="report-note"
          className="control min-h-24"
          maxLength={512}
          value={note}
          disabled={saving}
          onChange={(event) => {
            setNote(event.target.value);
            setConfirmed(false);
          }}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="report-reason">Report review reason</Label>
        <Input
          id="report-reason"
          required
          minLength={3}
          maxLength={512}
          value={reason}
          disabled={saving}
          onChange={(event) => {
            setReason(event.target.value);
            setConfirmed(false);
          }}
          className="min-h-9"
        />
      </div>
      <label className="flex min-h-9 items-center gap-3 text-sm">
        <Checkbox
          required
          checked={confirmed}
          disabled={saving}
          onCheckedChange={(checked) => setConfirmed(checked === true)}
        />
        I checked this report and review decision.
      </label>
      <div className="flex flex-wrap gap-3">
        <Button className="min-h-9" disabled={saving || !confirmed}>
          {saving ? 'Committing…' : 'Save report review'}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="min-h-9"
          disabled={saving}
          onClick={close}
        >
          Close review
        </Button>
      </div>
    </form>
  );
}

function ModerationActivity({
  api,
  revision,
}: {
  actor: { role: string };
  api: Api;
  revision: number;
}) {
  const [kind, setKind] = useState<'reports' | 'events'>('reports');
  const [cursor, setCursor] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [records, setRecords] = useState<List>(empty);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Data | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    api<List>(
      'moderation/' +
        kind +
        '?' +
        new URLSearchParams({ limit: '25', ...(cursor ? { cursor } : {}) }),
    )
      .then((value) => {
        if (current) setRecords(value);
      })
      .catch((failure) => {
        if (current) setError(failure.message);
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [kind, cursor, revision, refresh, api]);
  const columns =
    kind === 'reports'
      ? [
          ['target', 'Reported player'],
          ['reporter_account_id', 'Reported by'],
          ['text', 'Message'],
          ['status', 'Status'],
          ['created_at', 'When'],
        ]
      : [
          ['operation', 'Action'],
          ['target_id', 'Player'],
          ['actor_id', 'By'],
          ['reason', 'Reason'],
          ['created_at', 'When'],
        ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{kind === 'reports' ? 'Player reports' : 'Moderation history'}</CardTitle>
        <CardDescription>
          {kind === 'reports'
            ? 'Reports contain player-supplied usernames and text. Verify the account separately before enforcing a policy.'
            : 'Committed moderation activity and its before/after audit state.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2" aria-label="Moderation records">
          {(['reports', 'events'] as const).map((value) => (
            <Button
              key={value}
              variant={kind === value ? 'default' : 'outline'}
              className="min-h-9"
              aria-pressed={kind === value}
              onClick={() => {
                setKind(value);
                setCursor('');
                setHistory([]);
                setSelected(null);
              }}
            >
              {value === 'reports' ? 'Reports' : 'Moderation history'}
            </Button>
          ))}
        </div>
        {busy && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading moderation records…
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!busy && !error && (
          <>
            <p className="text-xs text-muted-foreground">{records.total} records</p>
            {!records.items.length ? (
              <p className="py-6 text-center text-sm text-muted-foreground">No records found.</p>
            ) : (
              <RecordList
                items={records.items}
                columns={columns
                  .map(([key]) => key)
                  .filter((key) => !['before', 'after', 'request_id'].includes(key))}
                action={
                  kind === 'reports'
                    ? (row) => (
                        <Button
                          variant="outline"
                          className="min-h-9"
                          onClick={() => setSelected(row)}
                          disabled={!/^[a-f0-9]{64}$/.test(String(row.report_id))}
                        >
                          Review
                        </Button>
                      )
                    : undefined
                }
              />
            )}
          </>
        )}
        <div className="flex justify-between">
          <Button
            variant="outline"
            className="min-h-9"
            disabled={busy || !history.length}
            onClick={() => {
              setCursor(history[history.length - 1]);
              setHistory((value) => value.slice(0, -1));
            }}
          >
            Previous records
          </Button>
          <Button
            variant="outline"
            className="min-h-9"
            disabled={busy || !records.next_cursor}
            onClick={() => {
              setHistory((value) => [...value, cursor]);
              setCursor(records.next_cursor!);
            }}
          >
            Next records
          </Button>
        </div>
        {selected && (
          <ReportReview
            key={String(selected.report_id)}
            report={selected}
            api={api}
            close={() => setSelected(null)}
            committed={() => setRefresh((value) => value + 1)}
          />
        )}
      </CardContent>
    </Card>
  );
}

export function ModerationWorkspace({
  actor,
  api,
  revision,
  mutate,
  saving = false,
}: {
  actor: { role: string };
  api: Api;
  revision: number;
  mutate?: (path: string, body: Data) => Promise<boolean>;
  saving?: boolean;
}) {
  const [version, setVersion] = useState(0);
  const refreshAll = useCallback(() => setVersion((value) => value + 1), []);
  const currentRevision = revision + version;
  return (
    <Tabs defaultValue="active" className="gap-3">
      <TabsList
        className="h-auto w-full flex-wrap justify-start gap-1 p-1"
        aria-label="Moderation sections"
      >
        {[
          ['active', 'Active restrictions'],
          ['players', 'Take action'],
          ['reports', 'Reports & history'],
          ['maintenance', 'Maintenance'],
          ['news', 'Login news'],
        ].map(([id, label]) => (
          <TabsTrigger key={id} value={id} className="flex-none px-3 text-xs sm:text-sm">
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="active">
        <PaginatedRecords
          title="Banned and muted players"
          path="moderation/active"
          revision={currentRevision}
          load={api as (path: string) => Promise<any>}
          description="Everyone currently restricted, why, and until when. Open a player to lift or change it."
          columns={['account_id', 'status', 'reason', 'until', 'last_actor_id', 'last_action_at']}
          render={{
            status: (row) => (
              <span className="flex gap-1">
                {row.banned ? <Badge variant="destructive">Banned</Badge> : null}
                {row.muted ? <Badge variant="secondary">Muted</Badge> : null}
              </span>
            ),
            reason: (row) => String((row.banned ? row.ban_reason : row.mute_reason) || '—'),
            until: (row) => {
              const at = row.banned ? row.ban_expires_at : row.mute_expires_at;
              return typeof at === 'number' ? new Date(at * 1000).toLocaleString() : 'Permanent';
            },
          }}
          onRowClick={(row) =>
            (window.location.hash = playerHref(String(row.account_id), 'moderation'))
          }
          emptyText="No one is banned or muted."
        />
      </TabsContent>
      <TabsContent value="players" className="grid gap-3">
        {mutate && (
          <AdminActions
            actor={actor}
            api={api as (path: string, body?: Data) => Promise<any>}
            mutate={mutate}
            saving={saving}
            target={null}
            kinds={['server']}
            title="Server actions"
            description="Affect everyone: server availability screens and reconnecting or relocating all players."
            exclude={['maintenance_countdown', 'publish_news']}
          />
        )}
        <UnsupportedActions api={api as (path: string, body?: Data) => Promise<any>} />
        <ModerationPanel
          actor={actor}
          api={api}
          revision={currentRevision}
          onCommitted={refreshAll}
        />
      </TabsContent>
      <TabsContent value="reports">
        <ModerationActivity actor={actor} api={api} revision={currentRevision} />
      </TabsContent>
      <TabsContent value="maintenance">
        <Maintenance actor={actor} api={api} revision={currentRevision} onCommitted={refreshAll} />
      </TabsContent>
      <TabsContent value="news">
        <NewsPanel actor={actor} api={api} revision={currentRevision} onCommitted={refreshAll} />
      </TabsContent>
    </Tabs>
  );
}

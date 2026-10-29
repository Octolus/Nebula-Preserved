import { FormSelect } from './form-select';
import { Checkbox } from './ui/checkbox';
import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Badge } from './ui/badge';
import {
  actionLabels,
  moderationBody,
  supportedActions,
  canSetStaffLabel,
  staffLabelBody,
  type ModerationAction,
} from '../lib/moderation';

type RecordData = Record<string, unknown>;
const expiryText = (value: unknown) =>
  typeof value === 'number' ? new Date(value * 1000).toLocaleString() : 'No scheduled expiry';

export function ModerationPanel({
  accountId,
  actor,
  api,
  revision,
  onCommitted,
}: {
  accountId?: string;
  actor: { role: string };
  api: (path: string, body?: RecordData) => Promise<RecordData>;
  revision: number;
  onCommitted?: () => void;
}) {
  const [query, setQuery] = useState('');
  const [target, setTarget] = useState(accountId || '');
  const [capabilities, setCapabilities] = useState<RecordData>({});
  const [status, setStatus] = useState<RecordData | null>(null);
  const [action, setAction] = useState<ModerationAction>('ban');
  const [reason, setReason] = useState('');
  const [expiry, setExpiry] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [label, setLabel] = useState('');
  const [labelReason, setLabelReason] = useState('');
  const [labelConfirmed, setLabelConfirmed] = useState(false);
  const actions = supportedActions(capabilities, actor.role);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    setStatus(null);
    (async () => {
      const caps = await api('capabilities');
      const state =
        target && caps.moderation_supported === true
          ? await api('users/' + encodeURIComponent(target) + '/moderation')
          : null;
      return [caps, state] as const;
    })()
      .then(([caps, state]) => {
        if (!current) return;
        if (state && state.account_id !== target)
          throw new Error('Player response did not match the target account.');
        setCapabilities(caps);
        setStatus(state);
        setLabel(typeof state?.staff_label === 'string' ? state.staff_label : '');
        setLabelConfirmed(false);
        const available = supportedActions(caps, actor.role);
        setAction((previous) => (available.includes(previous) ? previous : available[0] || 'ban'));
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
  }, [api, target, actor.role, revision, refresh]);

  async function submit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || saving || !confirmed || status?.account_id !== target || !actions.includes(action))
      return;
    setError('');
    setNotice('');
    try {
      const body = moderationBody(action, reason, expiry);
      setSaving(true);
      const result = await api('users/' + encodeURIComponent(target) + '/' + action, body);
      setNotice(
        `Moderation policy committed. Audit record ${result.audit_id ?? result.request_id}. Client delivery is reported separately.`,
      );
      setReason('');
      setExpiry('');
      setConfirmed(false);
      setRefresh((value) => value + 1);
      onCommitted?.();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function submitLabel(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      saving ||
      busy ||
      !labelConfirmed ||
      status?.account_id !== target ||
      !canSetStaffLabel(capabilities, actor.role)
    )
      return;
    setError('');
    setNotice('');
    try {
      const body = staffLabelBody(label, labelReason);
      setSaving(true);
      const result = await api('users/' + encodeURIComponent(target) + '/staff-label', body);
      setNotice(
        `Display label committed. Audit record ${result.audit_id ?? result.request_id}. Players receive it on their next label lookup; permissions are unchanged.`,
      );
      setLabelReason('');
      setLabelConfirmed(false);
      setRefresh((value) => value + 1);
      onCommitted?.();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const prefix = accountId ? 'player-moderation' : 'moderation';
  return (
    <Card>
      <CardHeader>
        <CardTitle>Player moderation</CardTitle>
        <CardDescription>
          Account policy is enforced by the preservation server. Panel permissions are separate from
          in-game roles.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!accountId && (
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              setTarget(query.trim());
              setConfirmed(false);
              setReason('');
              setExpiry('');
              setNotice('');
            }}
          >
            <div className="min-w-48 flex-1 space-y-2">
              <Label htmlFor={prefix + '-target'}>Player account ID</Label>
              <Input
                id={prefix + '-target'}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                required
                maxLength={128}
                className="min-h-11"
              />
            </div>
            <Button variant="outline" className="min-h-11" disabled={busy || saving}>
              Look up player
            </Button>
          </form>
        )}
        {busy && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading moderation state…
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive p-3 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="rounded-md border p-3 text-sm">
            {notice}
          </p>
        )}
        {!busy && !error && capabilities.moderation_supported !== true && (
          <p className="text-sm text-muted-foreground">
            This server does not advertise moderation support.
          </p>
        )}
        {status?.account_id === target && !busy && (
          <>
            <div className="space-y-3">
              <p className="break-all text-sm font-medium">{target}</p>
              <div className="flex flex-wrap gap-2">
                <Badge variant={status.banned === true ? 'destructive' : 'secondary'}>
                  {status.banned === true ? 'Banned' : 'Not banned'}
                </Badge>
                <Badge variant={status.muted === true ? 'destructive' : 'secondary'}>
                  {status.muted === true ? 'Muted' : 'Not muted'}
                </Badge>
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                {capabilities.staff_labels_supported === true && (
                  <div className="sm:col-span-2">
                    <dt className="text-muted-foreground">Staff display label</dt>
                    <dd className="break-words">{String(status.staff_label || 'None')}</dd>
                  </div>
                )}
                <div>
                  <dt className="text-muted-foreground">Ban expiry</dt>
                  <dd>{status.banned === true ? expiryText(status.ban_expires_at) : '—'}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Mute expiry</dt>
                  <dd>{status.muted === true ? expiryText(status.mute_expires_at) : '—'}</dd>
                </div>
                {status.banned === true && (
                  <div>
                    <dt className="text-muted-foreground">Ban reason</dt>
                    <dd className="break-words">{String(status.ban_reason || '—')}</dd>
                  </div>
                )}
                {status.muted === true && (
                  <div>
                    <dt className="text-muted-foreground">Mute reason</dt>
                    <dd className="break-words">{String(status.mute_reason || '—')}</dd>
                  </div>
                )}
              </dl>
            </div>
            {actions.length > 0 && (
              <form className="space-y-4 border-t pt-4" onSubmit={submit}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor={prefix + '-action'}>Moderation action</Label>
                    <FormSelect
                      id={prefix + '-action'}
                      disabled={saving}
                      value={action}
                      options={actions.map((value) => ({ value, label: actionLabels[value] }))}
                      onValueChange={(value) => {
                        setAction(value as ModerationAction);
                        setConfirmed(false);
                      }}
                    />
                  </div>
                  {(action === 'ban' || action === 'mute') && (
                    <div className="space-y-2">
                      <Label htmlFor={prefix + '-expiry'}>Expiry in UTC (optional)</Label>
                      <Input
                        id={prefix + '-expiry'}
                        type="datetime-local"
                        step="60"
                        disabled={saving}
                        value={expiry}
                        onChange={(event) => {
                          setExpiry(event.target.value);
                          setConfirmed(false);
                        }}
                        className="min-h-11"
                      />
                      <p className="text-xs text-muted-foreground">
                        Leave empty to keep the policy until it is removed.
                      </p>
                    </div>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor={prefix + '-reason'}>Moderation reason</Label>
                  <Input
                    id={prefix + '-reason'}
                    required
                    minLength={3}
                    maxLength={512}
                    disabled={saving}
                    value={reason}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setConfirmed(false);
                    }}
                    className="min-h-11"
                  />
                </div>
                <label className="flex min-h-11 items-center gap-3 text-sm">
                  <Checkbox
                    checked={confirmed}
                    disabled={saving}
                    onCheckedChange={(checked) => setConfirmed(checked === true)}
                    required
                  />
                  <span>
                    I checked account <span className="break-all font-medium">{target}</span> and
                    this action.
                  </span>
                </label>
                <Button
                  className="min-h-11"
                  variant={action === 'ban' || action === 'kick' ? 'destructive' : 'default'}
                  disabled={saving || !confirmed}
                >
                  {saving ? 'Committing…' : actionLabels[action]}
                </Button>
              </form>
            )}
            {canSetStaffLabel(capabilities, actor.role) && (
              <form onSubmit={submitLabel} className="space-y-4 border-t pt-4">
                <div>
                  <h3 className="font-semibold">Staff display label</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Display text only. This does not grant game commands or panel permissions.
                    Players receive it on their next label lookup.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor={prefix + '-label'}>Display label (empty clears it)</Label>
                  <Input
                    id={prefix + '-label'}
                    value={label}
                    disabled={saving}
                    maxLength={32}
                    onChange={(event) => {
                      setLabel(event.target.value);
                      setLabelConfirmed(false);
                    }}
                    className="min-h-11"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={prefix + '-label-reason'}>Display label reason</Label>
                  <Input
                    id={prefix + '-label-reason'}
                    value={labelReason}
                    disabled={saving}
                    required
                    minLength={3}
                    maxLength={512}
                    onChange={(event) => {
                      setLabelReason(event.target.value);
                      setLabelConfirmed(false);
                    }}
                    className="min-h-11"
                  />
                </div>
                <label className="flex min-h-11 items-center gap-3 text-sm">
                  <Checkbox
                    required
                    checked={labelConfirmed}
                    disabled={saving}
                    onCheckedChange={(checked) => setLabelConfirmed(checked === true)}
                  />
                  I checked the display label for account{' '}
                  <span className="break-all">{target}</span>.
                </label>
                <Button className="min-h-11" disabled={saving || !labelConfirmed}>
                  {saving ? 'Committing…' : 'Set display label'}
                </Button>
              </form>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

import { RecordList } from './record-list';
import { Textarea } from './ui/textarea';
import { Checkbox } from './ui/checkbox';
import { useEffect, useState } from 'react';
import { canPublishNews, newsBody, newsIdPattern, moderationReason } from '../lib/moderation';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';

type Data = Record<string, unknown>;
type Api = <T = Data>(path: string, body?: Data) => Promise<T>;
type List = { items: Data[]; total: number; next_cursor: string | null };
const empty: List = { items: [], total: 0, next_cursor: null };

export function NewsPanel({
  actor,
  api,
  revision,
  onCommitted,
}: {
  actor: { role: string };
  api: Api;
  revision: number;
  onCommitted?: () => void;
}) {
  const [caps, setCaps] = useState<Data>({});
  const [records, setRecords] = useState<List>(empty);
  const [cursor, setCursor] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [expiry, setExpiry] = useState('');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [archive, setArchive] = useState<Data | null>(null);
  const [archiveReason, setArchiveReason] = useState('');
  const [archiveConfirmed, setArchiveConfirmed] = useState(false);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const canWrite = canPublishNews(caps, actor.role);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    (async () => {
      const capabilities = await api('capabilities');
      const data =
        capabilities.news_supported === true
          ? await api<List>(
              'moderation/news?' +
                new URLSearchParams({ limit: '25', ...(cursor ? { cursor } : {}) }),
            )
          : empty;
      if (current) {
        setCaps(capabilities);
        setRecords(data);
      }
    })()
      .catch((failure) => {
        if (current) setError(failure.message);
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [api, cursor, revision, refresh]);
  async function publish(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || saving || busy || !confirmed) return;
    setError('');
    setNotice('');
    try {
      const body = newsBody(text, expiry, reason);
      setSaving(true);
      const result = await api('moderation/news', body);
      setNotice(
        `News committed. Audit record ${result.audit_id ?? result.request_id}. It appears on the next client news fetch.`,
      );
      setText('');
      setExpiry('');
      setReason('');
      setConfirmed(false);
      setCursor('');
      setHistory([]);
      setRefresh((value) => value + 1);
      onCommitted?.();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function archiveNews(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !canWrite ||
      saving ||
      busy ||
      !archiveConfirmed ||
      !archive ||
      !newsIdPattern.test(String(archive.news_id))
    )
      return;
    setError('');
    setNotice('');
    try {
      const body = { reason: moderationReason(archiveReason) };
      setSaving(true);
      const result = await api('moderation/news/' + archive.news_id + '/archive', body);
      setNotice(
        `News archive committed. Audit record ${result.audit_id ?? result.request_id}. Clients refresh news on their next fetch.`,
      );
      setArchive(null);
      setArchiveReason('');
      setArchiveConfirmed(false);
      setRefresh((value) => value + 1);
      onCommitted?.();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Login news</CardTitle>
        <CardDescription>
          News is returned by the original client news fetch. This is not a live broadcast or an
          immediate popup.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {busy && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading news…
          </p>
        )}
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
        {!busy && caps.news_supported !== true && (
          <p className="text-sm text-muted-foreground">
            This server does not advertise login news support.
          </p>
        )}
        {!busy && !error && caps.news_supported === true && (
          <>
            <p className="text-xs text-muted-foreground">{records.total} records</p>
            {!records.items.length ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No news records found.
              </p>
            ) : (
              <RecordList
                items={records.items.map((row) => ({
                  ...row,
                  status: row.active === true || row.active === 1 ? 'Active' : 'Inactive',
                }))}
                columns={['news_id', 'text', 'date_label', 'expires_at', 'status']}
                action={
                  canWrite
                    ? (row) => (
                        <Button
                          className="min-h-9"
                          variant="outline"
                          disabled={
                            saving ||
                            !(row.active === true || row.active === 1) ||
                            !newsIdPattern.test(String(row.news_id))
                          }
                          onClick={() => {
                            setArchive(row);
                            setArchiveReason('');
                            setArchiveConfirmed(false);
                          }}
                        >
                          Archive
                        </Button>
                      )
                    : undefined
                }
              />
            )}
            <div className="flex justify-between">
              <Button
                className="min-h-9"
                variant="outline"
                disabled={saving || !history.length}
                onClick={() => {
                  setCursor(history[history.length - 1]);
                  setHistory((value) => value.slice(0, -1));
                }}
              >
                Previous news
              </Button>
              <Button
                className="min-h-9"
                variant="outline"
                disabled={saving || !records.next_cursor}
                onClick={() => {
                  setHistory((value) => [...value, cursor]);
                  setCursor(records.next_cursor!);
                }}
              >
                Next news
              </Button>
            </div>
          </>
        )}
        {canWrite && (
          <form onSubmit={publish} className="space-y-4 border-t pt-4">
            <h3 className="font-semibold">Publish login news</h3>
            <div className="space-y-2">
              <Label htmlFor="news-text">News text</Label>
              <Textarea
                id="news-text"
                className="control min-h-24"
                required
                maxLength={1000}
                disabled={saving}
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  setConfirmed(false);
                }}
              />
              <p className="text-xs text-muted-foreground">
                One paragraph, up to 1000 characters. The server supplies the UTC date label.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="news-expiry">News expiry in UTC (optional)</Label>
              <Input
                id="news-expiry"
                className="min-h-9"
                type="datetime-local"
                step="60"
                disabled={saving}
                value={expiry}
                onChange={(event) => {
                  setExpiry(event.target.value);
                  setConfirmed(false);
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="news-reason">News publication reason</Label>
              <Input
                id="news-reason"
                className="min-h-9"
                required
                minLength={3}
                maxLength={512}
                disabled={saving}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setConfirmed(false);
                }}
              />
            </div>
            <label className="flex min-h-9 items-center gap-3 text-sm">
              <Checkbox
                required
                disabled={saving}
                checked={confirmed}
                onCheckedChange={(checked) => setConfirmed(checked === true)}
              />
              I checked this news for the server.
            </label>
            <Button className="min-h-9" disabled={busy || saving || !confirmed}>
              {saving ? 'Committing…' : 'Publish news'}
            </Button>
          </form>
        )}
        {archive && canWrite && (
          <form onSubmit={archiveNews} className="space-y-4 rounded-md border p-4">
            <h3 className="font-semibold">Archive news</h3>
            <p className="break-all text-xs text-muted-foreground">{String(archive.news_id)}</p>
            <p className="break-words text-sm">{String(archive.text)}</p>
            <div className="space-y-2">
              <Label htmlFor="news-archive-reason">News archive reason</Label>
              <Input
                id="news-archive-reason"
                className="min-h-9"
                required
                minLength={3}
                maxLength={512}
                disabled={saving}
                value={archiveReason}
                onChange={(event) => {
                  setArchiveReason(event.target.value);
                  setArchiveConfirmed(false);
                }}
              />
            </div>
            <label className="flex min-h-9 items-center gap-3 text-sm">
              <Checkbox
                required
                disabled={saving}
                checked={archiveConfirmed}
                onCheckedChange={(checked) => setArchiveConfirmed(checked === true)}
              />
              I checked this news archive decision.
            </label>
            <div className="flex gap-3">
              <Button className="min-h-9" disabled={busy || saving || !archiveConfirmed}>
                {saving ? 'Committing…' : 'Confirm archive'}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="min-h-9"
                disabled={saving}
                onClick={() => setArchive(null)}
              >
                Cancel archive
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

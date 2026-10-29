import { useEffect, useId, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Checkbox } from './ui/checkbox';
import { Badge } from './ui/badge';
import { FormSelect } from './form-select';
import { RecordList } from './record-list';
import { fieldLabel, formatCell, type Row } from '../lib/panel';

export type List = { items: Row[]; next_cursor: string | null; total: number };
export const empty: List = { items: [], next_cursor: null, total: 0 };
export function Details({ data }: { data: Row }) {
  return (
    <dl className="grid gap-x-4 gap-y-3 text-sm sm:grid-cols-2">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs capitalize text-muted-foreground">{fieldLabel(key)}</dt>
          <dd className="mt-1 break-words font-medium [overflow-wrap:anywhere]">
            {formatCell(key, value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function PaginatedRecords({
  title,
  path,
  revision,
  load,
  columns,
  description,
}: {
  title: string;
  path: string;
  revision: number;
  load: (path: string) => Promise<List>;
  columns?: string[];
  description?: string;
}) {
  const [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [records, setRecords] = useState<List>(empty),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    load(path + '?' + new URLSearchParams({ limit: '25', ...(cursor ? { cursor } : {}) }))
      .then((data) => {
        if (current) setRecords(data);
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
  }, [path, cursor, revision, load]);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {title}
          <Badge variant="secondary">{records.total}</Badge>
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-3">
        {busy ? (
          <p role="status" className="text-sm">
            Loading records…
          </p>
        ) : error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : (
          <RecordList items={records.items} columns={columns} />
        )}
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy || !history.length}
            onClick={() => {
              setCursor(history.at(-1)!);
              setHistory((h) => h.slice(0, -1));
            }}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground">Page {history.length + 1}</span>
          <Button
            variant="outline"
            className="min-h-11"
            disabled={busy || !records.next_cursor}
            onClick={() => {
              setHistory((h) => [...h, cursor]);
              setCursor(records.next_cursor!);
            }}
          >
            Next
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
type Field = {
  name: string;
  label: string;
  type?: string;
  options?: string[];
  optional?: boolean;
  hint?: string;
};
export function ChangeForm({
  title,
  description,
  fields,
  submit,
  busy,
  defaults = {},
}: {
  title: string;
  description: string;
  fields: Field[];
  submit: (data: Record<string, string>) => Promise<boolean>;
  busy: boolean;
  defaults?: Record<string, string>;
}) {
  const id = useId();
  const [confirmed, setConfirmed] = useState(false),
    [values, setValues] = useState<Record<string, string>>({}),
    [error, setError] = useState('');
  const value = (field: Field) =>
    values[field.name] ?? defaults[field.name] ?? field.options?.[0] ?? '';
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy || !confirmed) return;
            setError('');
            const body = Object.fromEntries(new FormData(event.currentTarget)) as Record<
              string,
              string
            >;
            try {
              if (await submit(body)) {
                setValues({});
                setConfirmed(false);
              }
            } catch (failure) {
              setError((failure as Error).message);
            }
          }}
        >
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <fieldset
            disabled={busy}
            className="grid min-w-0 gap-3"
            onChange={() => setConfirmed(false)}
          >
            {fields.map((field) => (
              <div key={field.name} className="grid min-w-0 gap-1.5">
                <Label htmlFor={id + field.name}>{field.label}</Label>
                {field.options ? (
                  <FormSelect
                    id={id + field.name}
                    name={field.name}
                    value={value(field)}
                    options={field.options}
                    onValueChange={(next) => {
                      setValues((v) => ({ ...v, [field.name]: next }));
                      setConfirmed(false);
                    }}
                  />
                ) : (
                  <Input
                    id={id + field.name}
                    name={field.name}
                    type={field.type || 'text'}
                    required={!field.optional}
                    className="min-h-11"
                    value={value(field)}
                    onChange={(event) =>
                      setValues((v) => ({ ...v, [field.name]: event.target.value }))
                    }
                  />
                )}
                {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
              </div>
            ))}
            <div className="grid gap-1.5">
              <Label htmlFor={id + 'reason'}>Reason for this change</Label>
              <Input
                id={id + 'reason'}
                name="reason"
                required
                minLength={3}
                maxLength={512}
                className="min-h-11"
                value={values.reason || ''}
                onChange={(event) => setValues((v) => ({ ...v, reason: event.target.value }))}
              />
            </div>
          </fieldset>
          <label className="flex min-h-11 items-center gap-3 text-sm">
            <Checkbox
              checked={confirmed}
              onCheckedChange={(next) => setConfirmed(next === true)}
              disabled={busy}
              required
            />
            I checked the target account and change.
          </label>
          <Button disabled={busy || !confirmed} className="min-h-11 sm:justify-self-start">
            {busy ? 'Saving…' : title}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

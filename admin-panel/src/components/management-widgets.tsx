import { useEffect, useId, useState, type ReactNode } from 'react';
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
/** Coerce any API reply into a list page so a malformed response can't crash a view. */
export function asList(data: unknown): List {
  const value = (data && typeof data === 'object' ? data : {}) as Partial<List>;
  const items = Array.isArray(value.items) ? value.items : [];
  return {
    items,
    total: typeof value.total === 'number' ? value.total : items.length,
    next_cursor: typeof value.next_cursor === 'string' ? value.next_cursor : null,
  };
}
export function Details({ data }: { data: Row }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{fieldLabel(key)}</dt>
          <dd className="break-words font-medium [overflow-wrap:anywhere]">
            {formatCell(key, value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Pager({
  history,
  next,
  busy,
  back,
  forward,
}: {
  history: string[];
  next: string | null;
  busy: boolean;
  back: () => void;
  forward: () => void;
}) {
  if (!history.length && !next) return null;
  return (
    <div className="flex items-center justify-between gap-2">
      <Button variant="outline" size="sm" disabled={busy || !history.length} onClick={back}>
        Previous
      </Button>
      <span className="text-xs text-muted-foreground">Page {history.length + 1}</span>
      <Button variant="outline" size="sm" disabled={busy || !next} onClick={forward}>
        Next
      </Button>
    </div>
  );
}

export function PaginatedRecords({
  title,
  path,
  revision,
  load,
  columns,
  description,
  renderItems,
  params = {},
  action,
  onRowClick,
  emptyText,
  headerAction,
  render,
}: {
  title: string;
  path: string;
  revision: number;
  load: (path: string) => Promise<List>;
  columns?: string[];
  description?: string;
  renderItems?: (items: Row[]) => ReactNode;
  params?: Record<string, string>;
  action?: (row: Row) => ReactNode;
  onRowClick?: (row: Row) => void;
  emptyText?: string;
  headerAction?: ReactNode;
  render?: Record<string, (row: Row) => ReactNode>;
}) {
  const extra = JSON.stringify(params);
  const [cursor, setCursor] = useState(''),
    [history, setHistory] = useState<string[]>([]),
    [records, setRecords] = useState<List>(empty),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    setCursor('');
    setHistory([]);
  }, [path, extra]);
  useEffect(() => {
    let current = true;
    setBusy(true);
    setError('');
    load(
      path +
        '?' +
        new URLSearchParams({ limit: '25', ...JSON.parse(extra), ...(cursor ? { cursor } : {}) }),
    )
      .then((data) => {
        if (current) setRecords(asList(data));
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
  }, [path, cursor, revision, load, extra]);
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          {title}
          <Badge variant="secondary">
            {Number(records.total ?? records.items?.length ?? 0).toLocaleString()}
          </Badge>
          {headerAction && <span className="ml-auto">{headerAction}</span>}
        </CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-3 px-4">
        {busy && !records.items.length ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading…
          </p>
        ) : error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : renderItems ? (
          renderItems(records.items)
        ) : (
          <RecordList
            items={records.items}
            columns={columns}
            action={action}
            onRowClick={onRowClick}
            emptyText={emptyText}
            render={render}
          />
        )}
        <Pager
          history={history}
          next={records.next_cursor}
          busy={busy}
          back={() => {
            setCursor(history.at(-1)!);
            setHistory((h) => h.slice(0, -1));
          }}
          forward={() => {
            setHistory((h) => [...h, cursor]);
            setCursor(records.next_cursor!);
          }}
        />
      </CardContent>
    </Card>
  );
}
type Field = {
  name: string;
  label: string;
  type?: string;
  options?: (string | { value: string; label: string })[];
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
  confirmationLabel = 'I checked the target account and change.',
  requireReason = false,
  confirm = false,
  submitLabel,
  bare = false,
}: {
  title: string;
  description?: string;
  fields: Field[];
  submit: (data: Record<string, string>) => Promise<boolean>;
  busy: boolean;
  defaults?: Record<string, string>;
  confirmationLabel?: string;
  /** Moderation and panel-access changes must state why; routine edits need not. */
  requireReason?: boolean;
  confirm?: boolean;
  submitLabel?: string;
  bare?: boolean;
}) {
  const id = useId();
  const [checked, setChecked] = useState(false),
    [values, setValues] = useState<Record<string, string>>({}),
    [error, setError] = useState('');
  const confirmed = !confirm || checked;
  const value = (field: Field) => {
    const first = field.options?.[0];
    return (
      values[field.name] ??
      defaults[field.name] ??
      (typeof first === 'string' ? first : first?.value) ??
      ''
    );
  };
  const form = (
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
            setChecked(false);
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
        className="grid min-w-0 gap-3 sm:grid-cols-2"
        onChange={() => setChecked(false)}
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
                  setChecked(false);
                }}
              />
            ) : (
              <Input
                id={id + field.name}
                name={field.name}
                type={field.type || 'text'}
                required={!field.optional}
                className="min-h-9"
                value={value(field)}
                onChange={(event) => setValues((v) => ({ ...v, [field.name]: event.target.value }))}
              />
            )}
            {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
          </div>
        ))}
        {requireReason && (
          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor={id + 'reason'}>Reason</Label>
            <Input
              id={id + 'reason'}
              name="reason"
              required
              minLength={3}
              maxLength={512}
              className="min-h-9"
              value={values.reason || ''}
              onChange={(event) => setValues((v) => ({ ...v, reason: event.target.value }))}
            />
          </div>
        )}
      </fieldset>
      {confirm && (
        <label className="flex min-h-9 items-center gap-3 text-sm">
          <Checkbox
            checked={checked}
            onCheckedChange={(next) => setChecked(next === true)}
            disabled={busy}
            required
          />
          {confirmationLabel}
        </label>
      )}
      <Button size="sm" disabled={busy || !confirmed} className="sm:justify-self-start">
        {busy ? 'Saving…' : submitLabel || title}
      </Button>
    </form>
  );
  if (bare) return form;
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="px-4">{form}</CardContent>
    </Card>
  );
}

/** Two-step destructive button: first click arms, second click runs. */
export function ConfirmButton({
  label,
  confirmLabel = 'Click again to confirm',
  onConfirm,
  disabled,
  variant = 'outline',
}: {
  label: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void | Promise<unknown>;
  disabled?: boolean;
  variant?: 'outline' | 'destructive' | 'ghost';
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(timer);
  }, [armed]);
  return (
    <Button
      type="button"
      size="sm"
      variant={armed ? 'destructive' : variant}
      disabled={disabled}
      onClick={() => {
        if (!armed) return setArmed(true);
        setArmed(false);
        void onConfirm();
      }}
    >
      {armed ? confirmLabel : label}
    </Button>
  );
}

/** Search players by name and pick one; staff never type account IDs. */
export function PlayerPicker({
  api,
  onPick,
  placeholder = 'Search players by name…',
}: {
  api: (path: string) => Promise<List>;
  onPick: (row: Row) => void;
  placeholder?: string;
}) {
  const id = useId();
  const [query, setQuery] = useState(''),
    [results, setResults] = useState<Row[]>([]),
    [open, setOpen] = useState(false);
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      api('users?' + new URLSearchParams({ q: query.trim(), limit: '8' }))
        .then((data) => current && setResults(data.items))
        .catch(() => current && setResults([]));
    }, 200);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [api, query]);
  return (
    <div className="relative">
      <Label className="sr-only" htmlFor={id}>
        Find player
      </Label>
      <Input
        id={id}
        value={query}
        autoComplete="off"
        placeholder={placeholder}
        className="min-h-9"
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
      />
      {open && results.length > 0 && (
        <ul className="absolute z-40 mt-1 max-h-72 w-full overflow-auto rounded-md border bg-popover p-1 shadow-md">
          {results.map((row) => (
            <li key={String(row.account_id)}>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onPick(row);
                  setQuery('');
                  setOpen(false);
                }}
              >
                <span className="min-w-0 truncate font-medium">
                  {String(row.username || row.account_id)}
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  {(row.banned === 1 || row.banned === true) && (
                    <Badge variant="destructive">Banned</Badge>
                  )}
                  {(row.online === 1 || row.online === true) && <Badge>Online</Badge>}
                  <span className="font-mono text-[11px] text-muted-foreground">
                    …{String(row.account_id).slice(-6)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Small labelled stat used in headers and overview tiles. */
export function Stat({
  label,
  value,
  href,
  tone,
}: {
  label: string;
  value: ReactNode;
  href?: string;
  tone?: 'danger';
}) {
  const body = (
    <>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={
          'text-xl font-semibold tabular-nums ' + (tone === 'danger' ? 'text-destructive' : '')
        }
      >
        {value}
      </p>
    </>
  );
  return href ? (
    <a href={href} className="rounded-lg border bg-card p-3 transition-colors hover:bg-accent">
      {body}
    </a>
  ) : (
    <div className="rounded-lg border bg-card p-3">{body}</div>
  );
}

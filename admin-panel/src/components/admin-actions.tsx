import { useEffect, useId, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Textarea } from './ui/textarea';
import { Checkbox } from './ui/checkbox';
import { FormSelect } from './form-select';
import type { Row } from '../lib/panel';

type Api = (path: string, body?: Row) => Promise<any>;
type Mutate = (path: string, body: Row) => Promise<boolean>;
type Option = { value: string; label: string };
export type ActionField = {
  name: string;
  type?: string;
  label?: string;
  required?: boolean;
  nullable?: boolean;
  options?: Option[];
  options_source?: string;
  option_value?: string;
  option_label?: string;
  default?: unknown;
  min?: number;
  max?: number;
  max_length?: number;
  allow_empty?: boolean;
};
export type AdminAction = {
  id: string;
  label?: string;
  permission?: string;
  target?: string;
  path: string;
  fixed_body?: Row;
  fields?: ActionField[];
  requires_reason?: boolean;
  destructive?: boolean;
  live_only?: boolean;
  client_effect?: string;
  allowed?: boolean;
};

/** Server-advertised admin actions the current operator may use. */
export function adminActions(caps: Row): AdminAction[] {
  return Array.isArray(caps.admin_actions)
    ? (caps.admin_actions as AdminAction[]).filter(
        (a) => a && typeof a.id === 'string' && a.allowed !== false,
      )
    : [];
}

const NULL = '__null__';

function useOptions(api: Api, field: ActionField) {
  const [options, setOptions] = useState<Option[]>(field.options || []);
  useEffect(() => {
    if (!field.options_source) return;
    api(field.options_source)
      .then((data) => {
        const items = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [];
        setOptions(
          (items as Row[]).map((row) => ({
            value: String(row[field.option_value || 'id']),
            label:
              String(row[field.option_label || 'label'] ?? row[field.option_value || 'id']) +
              (row.available === false
                ? ' (starts on demand)'
                : typeof row.players === 'number' && row.players
                  ? ` · ${row.players} online`
                  : ''),
          })),
        );
      })
      .catch(() => {});
  }, [api, field.options_source, field.option_value, field.option_label]);
  return field.nullable && !field.required ? [{ value: NULL, label: 'None' }, ...options] : options;
}

function FieldInput({
  field,
  value,
  setValue,
  api,
}: {
  field: ActionField;
  value: unknown;
  setValue: (value: unknown) => void;
  api: Api;
}) {
  const id = useId();
  const options = useOptions(api, field);
  // The select shows its first option; record it so submit matches what is displayed.
  useEffect(() => {
    if (field.type === 'enum' && value === undefined && options.length)
      setValue(options[0].value === NULL ? null : options[0].value);
  }, [field.type, value, options, setValue]);
  const label = field.label || field.name.replaceAll('_', ' ');
  let control;
  if (field.type === 'enum')
    control = options.length ? (
      <FormSelect
        id={id}
        value={value === null ? NULL : String(value ?? options[0].value)}
        options={options}
        onValueChange={(next) => setValue(next === NULL ? null : next)}
      />
    ) : (
      <p className="text-xs text-muted-foreground">Loading options…</p>
    );
  else if (field.type === 'multi_enum') {
    const chosen = new Set(Array.isArray(value) ? (value as string[]) : []);
    control = (
      <div className="flex flex-wrap gap-3">
        {options.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={chosen.has(option.value)}
              onCheckedChange={(on) => {
                const next = new Set(chosen);
                if (on === true) next.add(option.value);
                else next.delete(option.value);
                setValue([...next]);
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    );
  } else if (field.type === 'boolean')
    control = (
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={value === true} onCheckedChange={(on) => setValue(on === true)} />
        Yes
      </label>
    );
  else if (field.type === 'textarea')
    control = (
      <Textarea
        id={id}
        value={String(value ?? '')}
        maxLength={field.max_length}
        onChange={(e) => setValue(e.target.value)}
        className="min-h-20"
      />
    );
  else if (field.type === 'utc_timestamp')
    control = (
      <Input
        id={id}
        type="datetime-local"
        value={String(value ?? '')}
        onChange={(e) => setValue(e.target.value)}
        className="min-h-9"
      />
    );
  else
    control = (
      <Input
        id={id}
        type={field.type === 'integer' ? 'number' : 'text'}
        min={field.min}
        max={field.max}
        maxLength={field.max_length}
        value={String(value ?? '')}
        required={field.required && !field.allow_empty}
        onChange={(e) => setValue(e.target.value)}
        className="min-h-9"
      />
    );
  return (
    <div className="grid min-w-0 gap-1.5">
      <Label htmlFor={id}>
        {field.type === 'utc_timestamp' ? label.replace(/\s*\(UTC seconds[^)]*\)/, '') : label}
        {!field.required && (
          <span className="ml-1 text-xs font-normal text-muted-foreground">optional</span>
        )}
      </Label>
      {control}
      {field.type === 'utc_timestamp' && (
        <p className="text-xs text-muted-foreground">
          Your local time. Leave empty for no end date.
        </p>
      )}
    </div>
  );
}

function initial(field: ActionField): unknown {
  if (field.default !== undefined) return field.default;
  if (field.type === 'multi_enum') return [];
  if (field.type === 'boolean') return false;
  if (field.type === 'enum' && field.nullable && !field.required) return null;
  return undefined;
}

function encode(
  field: ActionField,
  value: unknown,
): { skip?: boolean; value?: unknown; error?: string } {
  const name = field.label || field.name;
  if (field.type === 'utc_timestamp') {
    if (!value) return field.nullable ? { value: null } : { skip: true };
    const seconds = Math.floor(new Date(String(value)).getTime() / 1000);
    return Number.isFinite(seconds)
      ? { value: seconds }
      : { error: 'Choose a valid date for ' + name };
  }
  if (field.type === 'integer') {
    if (value === undefined || value === '')
      return field.required ? { error: name + ' is required' } : { skip: true };
    const number = Number(value);
    return Number.isInteger(number)
      ? { value: number }
      : { error: name + ' must be a whole number' };
  }
  if (value === undefined)
    return field.required && !field.allow_empty ? { error: name + ' is required' } : { skip: true };
  if (value === '' && field.allow_empty) return { value: '' };
  if (value === '' && !field.required) return { skip: true };
  return { value };
}

function ActionForm({
  action,
  path,
  api,
  mutate,
  saving,
  done,
}: {
  action: AdminAction;
  path: string;
  api: Api;
  mutate: Mutate;
  saving: boolean;
  done: () => void;
}) {
  const fields = action.fields || [];
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(fields.map((field) => [field.name, initial(field)])),
  );
  const [reason, setReason] = useState(''),
    [armed, setArmed] = useState(false),
    [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    const body: Row = { ...(action.fixed_body || {}) };
    for (const field of fields) {
      const result = encode(field, values[field.name]);
      if (result.error) return setError(result.error);
      if (!result.skip) body[field.name] = result.value;
    }
    if (action.requires_reason && reason.trim().length < 3)
      return setError('Give a reason (at least 3 characters).');
    if (reason.trim()) body.reason = reason.trim();
    if (action.destructive && !armed) return setArmed(true);
    if (await mutate(path, body)) {
      setReason('');
      setArmed(false);
      done();
    }
  }
  return (
    <form onSubmit={submit} className="grid gap-3 rounded-md border p-3">
      {action.client_effect && (
        <p className="text-xs text-muted-foreground">{action.client_effect}</p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <FieldInput
            key={field.name}
            field={field}
            value={values[field.name]}
            setValue={(value) => {
              setArmed(false);
              setValues((v) => ({ ...v, [field.name]: value }));
            }}
            api={api}
          />
        ))}
        <div className="grid gap-1.5 sm:col-span-2">
          <Label htmlFor={action.id + '-reason'}>
            {action.requires_reason ? 'Reason' : 'Note'}
            {!action.requires_reason && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">optional</span>
            )}
          </Label>
          <Input
            id={action.id + '-reason'}
            value={reason}
            maxLength={512}
            onChange={(e) => setReason(e.target.value)}
            className="min-h-9"
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant={action.destructive && armed ? 'destructive' : 'default'}
          disabled={saving}
        >
          {saving
            ? 'Working…'
            : action.destructive && armed
              ? 'Click again to confirm'
              : action.label || action.id}
        </Button>
        {armed && (
          <Button size="sm" type="button" variant="ghost" onClick={() => setArmed(false)}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

/** Generic staff actions advertised by the server (move to world, reconnect, evacuate …). */
export function AdminActions({
  api,
  mutate,
  saving,
  target,
  kinds,
  online = true,
  title = 'Staff actions',
  description = 'Actions the original game client supports. Live actions reach the player within seconds.',
  exclude = [],
  bare = false,
}: {
  actor?: { role: string };
  api: Api;
  mutate: Mutate;
  saving: boolean;
  target: string | null;
  kinds: string[];
  online?: boolean;
  title?: string;
  description?: string;
  exclude?: string[];
  bare?: boolean;
}) {
  const [caps, setCaps] = useState<Row>({}),
    [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    api('capabilities')
      .then(setCaps)
      .catch(() => {});
  }, [api]);
  const actions = adminActions(caps).filter(
    (a) => kinds.includes(String(a.target || 'player')) && !exclude.includes(a.id),
  );
  if (!actions.length) return null;
  const pathFor = (action: AdminAction) =>
    action.path
      .replace('{account_id}', encodeURIComponent(target || ''))
      .replace('{instance_id}', encodeURIComponent(target || ''));
  const body = (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-1.5">
        {actions.map((action) => {
          const disabled = action.live_only && !online;
          return (
            <Button
              key={action.id}
              type="button"
              size="sm"
              variant={open === action.id ? 'default' : 'outline'}
              disabled={disabled}
              title={disabled ? 'Only while the player is online' : action.client_effect}
              onClick={() => setOpen(open === action.id ? null : action.id)}
            >
              {action.label || action.id}
              {action.live_only && (
                <Badge variant="secondary" className="ml-0.5 px-1 text-[10px]">
                  live
                </Badge>
              )}
            </Button>
          );
        })}
      </div>
      {actions
        .filter((a) => a.id === open)
        .map((action) => (
          <ActionForm
            key={action.id}
            action={action}
            path={pathFor(action)}
            api={api}
            mutate={mutate}
            saving={saving}
            done={() => setOpen(null)}
          />
        ))}
    </div>
  );
  if (bare) return body;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}

/** Things staff might expect that the original client cannot receive. */
export function UnsupportedActions({ api }: { api: Api }) {
  const [caps, setCaps] = useState<Row>({});
  useEffect(() => {
    api('capabilities')
      .then(setCaps)
      .catch(() => {});
  }, [api]);
  const items = Array.isArray(caps.admin_actions_unsupported)
    ? (caps.admin_actions_unsupported as Row[])
    : [];
  if (!items.length) return null;
  return (
    <details className="rounded-lg border px-4 py-3 text-sm">
      <summary className="cursor-pointer text-muted-foreground">
        Why can't I teleport, freeze or broadcast?
      </summary>
      <ul className="mt-2 grid gap-1.5">
        {items.map((row) => (
          <li key={String(row.id)}>
            <span className="font-medium">{String(row.id).replaceAll('_', ' ')}</span>
            <span className="text-muted-foreground"> — {String(row.reason || row.status)}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

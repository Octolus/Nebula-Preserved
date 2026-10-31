import type { ReactNode } from 'react';
import { display, entity, fieldLabel, formatCell, type Row } from '../lib/panel';
import { Card, CardContent } from './ui/card';
import { Badge } from './ui/badge';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from './ui/table';

const hidden = [
  'request_id',
  'before',
  'after',
  'before_json',
  'after_json',
  'account_name',
  'target_name',
  'target_type',
  'reporter_name',
  'target_account_id',
];

export function EntityCell({ field, row }: { field: string; row: Row }) {
  const named = entity(field, row);
  if (!named) return <>{formatCell(field, row[field])}</>;
  const label = named.href ? (
    <a href={named.href} className="font-medium underline-offset-4 hover:underline">
      {named.label}
    </a>
  ) : (
    <span className="font-medium">{named.label}</span>
  );
  return (
    <span className="inline-flex min-w-0 max-w-full flex-col">
      {label}
      {named.id && named.id !== named.label && (
        <span className="truncate font-mono text-[11px] text-muted-foreground" title={named.id}>
          {named.id}
        </span>
      )}
    </span>
  );
}

function cell(key: string, row: Row) {
  if (key === 'online')
    return (
      <Badge variant={row[key] === 1 || row[key] === true ? 'default' : 'outline'}>
        {formatCell(key, row[key])}
      </Badge>
    );
  if (key === 'delta' && typeof row.delta === 'number')
    return (
      <span className={'font-medium tabular-nums ' + (row.delta < 0 ? 'text-destructive' : '')}>
        {formatCell(key, row[key])} {row.currency === 'np' ? 'NP' : row.currency ? 'crystals' : ''}
      </span>
    );
  return <EntityCell field={key} row={row} />;
}

/** Field-level before/after instead of raw JSON blobs. */
export function ChangeSummary({ before, after }: { before: unknown; after: unknown }) {
  const object = (value: unknown) =>
    value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : null;
  const b = object(before),
    a = object(after);
  if (!b && !a) {
    if (before == null && after == null) return null;
    return (
      <p className="text-xs">
        {display(before)} → {display(after)}
      </p>
    );
  }
  const keys = Array.from(new Set([...Object.keys(b || {}), ...Object.keys(a || {})])).filter(
    (key) => JSON.stringify(b?.[key]) !== JSON.stringify(a?.[key]),
  );
  if (!keys.length) return <p className="text-xs text-muted-foreground">No field changed.</p>;
  return (
    <dl className="grid gap-1 text-xs">
      {keys.map((key) => (
        <div key={key} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-2">
          <dt className="truncate text-muted-foreground">{fieldLabel(key)}</dt>
          <dd className="min-w-0 break-words [overflow-wrap:anywhere]">
            <span className="text-muted-foreground line-through">{formatCell(key, b?.[key])}</span>{' '}
            → <span className="font-medium">{formatCell(key, a?.[key])}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function RecordList({
  items,
  columns,
  action,
  emptyText = 'Nothing here yet.',
  onRowClick,
  render = {},
}: {
  items: Row[];
  columns?: string[];
  action?: (row: Row) => ReactNode;
  emptyText?: string;
  onRowClick?: (row: Row) => void;
  render?: Record<string, (row: Row) => ReactNode>;
}) {
  const show = (key: string, row: Row) => (render[key] ? render[key](row) : cell(key, row));
  if (!items.length)
    return <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>;
  const keys =
    columns ||
    Array.from(new Set(items.flatMap((row) => Object.keys(row))))
      .filter((key) => !hidden.includes(key))
      .slice(0, 7);
  const hasChanges = items.some((row) => row.before !== undefined || row.after !== undefined);
  function changes(row: Row) {
    if (row.before === undefined && row.after === undefined) return null;
    return (
      <Accordion type="single" collapsible>
        <AccordionItem value="change" className="border-0">
          <AccordionTrigger className="py-1 text-xs">Changes</AccordionTrigger>
          <AccordionContent>
            <ChangeSummary before={row.before} after={row.after} />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    );
  }
  const clickable = onRowClick ? 'cursor-pointer' : '';
  return (
    <>
      <div className="grid min-w-0 gap-2 md:hidden">
        {items.map((row, index) => (
          <Card
            key={index}
            className={'gap-0 py-0 shadow-none ' + clickable}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
          >
            <CardContent className="p-3">
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.8fr)] gap-x-3 gap-y-1">
                {keys.map((key) => (
                  <div key={key} className="contents">
                    <dt className="self-center text-xs text-muted-foreground">{fieldLabel(key)}</dt>
                    <dd className="min-w-0 self-center break-words [overflow-wrap:anywhere]">
                      {show(key, row)}
                    </dd>
                  </div>
                ))}
              </dl>
              {changes(row)}
              {action && (
                <div className="mt-2 border-t pt-2" onClick={(event) => event.stopPropagation()}>
                  {action(row)}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="hidden min-w-0 overflow-x-auto rounded-md border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {keys.map((key) => (
                <TableHead key={key} className="h-8 text-xs">
                  {fieldLabel(key)}
                </TableHead>
              ))}
              {hasChanges && <TableHead className="h-8 text-xs">Changes</TableHead>}
              {action && <TableHead className="h-8 text-right text-xs">Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row, index) => (
              <TableRow
                key={index}
                className={clickable}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {keys.map((key) => (
                  <TableCell
                    key={key}
                    className="max-w-64 py-1.5 whitespace-normal break-words [overflow-wrap:anywhere]"
                  >
                    {show(key, row)}
                  </TableCell>
                ))}
                {hasChanges && (
                  <TableCell className="min-w-48 max-w-96 py-1.5">{changes(row)}</TableCell>
                )}
                {action && (
                  <TableCell
                    className="py-1.5 text-right"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {action(row)}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}

import type { ReactNode } from 'react';
import {
  display,
  fieldLabel,
  formatCell,
  playerHref,
  playerReference,
  type Row,
} from '../lib/panel';
import { Button } from './ui/button';
import { Card, CardContent } from './ui/card';
import { Badge } from './ui/badge';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion';
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from './ui/table';

export function RecordList({
  items,
  columns,
  action,
  emptyText = 'No records found.',
}: {
  items: Row[];
  columns?: string[];
  action?: (row: Row) => ReactNode;
  emptyText?: string;
}) {
  if (!items.length)
    return <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>;
  const keys =
    columns ||
    Array.from(new Set(items.flatMap((row) => Object.keys(row))))
      .filter(
        (key) => !['request_id', 'before', 'after', 'before_json', 'after_json'].includes(key),
      )
      .slice(0, 7);
  function value(key: string, row: Row) {
    const id = playerReference(key, row);
    if (id)
      return (
        <Button
          asChild
          variant="link"
          className="h-auto min-h-11 max-w-full justify-start whitespace-normal p-0 text-left"
        >
          <a href={playerHref(id)}>{String(row[key])}</a>
        </Button>
      );
    if (key === 'online')
      return (
        <Badge variant={row[key] === 1 || row[key] === true ? 'default' : 'secondary'}>
          {formatCell(key, row[key])}
        </Badge>
      );
    return formatCell(key, row[key]);
  }
  function changes(row: Row) {
    if (!row.before && !row.after) return null;
    return (
      <Accordion type="single" collapsible className="mt-2">
        <AccordionItem value="change" className="border-0">
          <AccordionTrigger className="min-h-11 py-2 text-xs">Before / after</AccordionTrigger>
          <AccordionContent>
            <div className="grid gap-3 sm:grid-cols-2">
              {['before', 'after'].map((key) => (
                <div key={key} className="min-w-0">
                  <p className="mb-1 font-medium capitalize">{key}</p>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify(row[key], null, 2) || '—'}
                  </pre>
                </div>
              ))}
            </div>
            <p className="mt-2 break-all text-xs text-muted-foreground">
              Request: {display(row.request_id)}
            </p>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    );
  }
  return (
    <>
      <div className="grid min-w-0 gap-2 md:hidden">
        {items.map((row, index) => (
          <Card key={index} className="gap-0 py-0 shadow-none">
            <CardContent className="p-3">
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-x-3 gap-y-1 text-sm">
                {keys.map((key) => (
                  <div key={key} className="contents">
                    <dt className="self-center text-xs capitalize text-muted-foreground">
                      {fieldLabel(key)}
                    </dt>
                    <dd className="min-w-0 self-center break-words [overflow-wrap:anywhere]">
                      {value(key, row)}
                    </dd>
                  </div>
                ))}
              </dl>
              {changes(row)}
              {action && <div className="mt-2 border-t pt-2">{action(row)}</div>}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="hidden min-w-0 overflow-x-auto rounded-md border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {keys.map((key) => (
                <TableHead key={key} className="capitalize">
                  {fieldLabel(key)}
                </TableHead>
              ))}
              {action && <TableHead>Actions</TableHead>}
              {items.some((row) => row.before || row.after) && <TableHead>Details</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row, index) => (
              <TableRow key={index}>
                {keys.map((key) => (
                  <TableCell
                    key={key}
                    className="max-w-64 break-words whitespace-normal text-sm [overflow-wrap:anywhere]"
                  >
                    {value(key, row)}
                  </TableCell>
                ))}
                {action && <TableCell>{action(row)}</TableCell>}
                {items.some((item) => item.before || item.after) && (
                  <TableCell className="min-w-48 max-w-80">{changes(row)}</TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}

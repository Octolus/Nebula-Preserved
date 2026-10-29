import { Card, CardHeader, CardTitle, CardDescription, CardFooter } from './ui/card';
export function SectionCards({ stats }: { stats: Record<string, unknown> }) {
  return (
    <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
      {[
        ['Players', stats.users, 'Registered accounts'],
        ['Online', stats.online, 'Current player sessions'],
        ['Purchases', stats.purchases, 'Recorded store purchases'],
        ['Admin actions', stats.audit_entries, 'Audited management changes'],
      ].map(([label, value, note]) => (
        <Card key={String(label)}>
          <CardHeader>
            <CardDescription>{String(label)}</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {typeof value === 'number' ? value.toLocaleString() : '—'}
            </CardTitle>
          </CardHeader>
          <CardFooter className="text-xs text-muted-foreground">{String(note)}</CardFooter>
        </Card>
      ))}
    </div>
  );
}

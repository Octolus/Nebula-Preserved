import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
export function LoginForm() {
  const [busy, setBusy] = useState(false),
    [ready, setReady] = useState(false),
    [error, setError] = useState('');
  useEffect(() => setReady(true), []);
  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardDescription>Nebula Preserved</CardDescription>
        <CardTitle className="text-xl">Server control</CardTitle>
        <CardDescription>Sign in with your operator account.</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          method="post"
          action="/api/login"
          className="grid gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!ready || busy) return;
            const data = new FormData(event.currentTarget);
            setBusy(true);
            setError('');
            try {
              const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: data.get('id'), password: data.get('password') }),
              });
              const payload = await response.json();
              if (!response.ok) throw new Error(payload.error?.message || 'Sign in failed');
              window.location.assign('/');
            } catch (failure) {
              setError((failure as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="id">Operator ID</Label>
            <Input
              id="id"
              name="id"
              autoComplete="username"
              required
              maxLength={128}
              disabled={!ready || busy}
              className="min-h-9"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={1024}
              disabled={!ready || busy}
              className="min-h-9"
            />
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={!ready || busy} className="min-h-9">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </CardContent>
      <CardFooter className="text-xs text-muted-foreground">
        Credentials are created by your server operator. No default password is provided.
      </CardFooter>
    </Card>
  );
}

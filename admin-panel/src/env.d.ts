/// <reference types="astro/client" />
declare namespace App {
  interface Locals {
    session: import('./lib/security').Session;
    csrf: string;
    actor: { id: string; role: 'owner' | 'admin' | 'moderator'; enabled: boolean };
  }
}

import { useEffect, useState } from 'react';
import {
  IconDashboard,
  IconUsers,
  IconReceipt,
  IconShield,
  IconPackage,
  IconBuildingStore,
  IconPlanet,
  IconLogout,
  IconActivity,
  IconShoppingBag,
  IconHistory,
  IconKey,
  IconMoon,
  IconSun,
} from '@tabler/icons-react';
import {
  Sidebar,
  useSidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
} from './ui/sidebar';
import { Button } from './ui/button';
export const groups = [
  {
    label: 'Community',
    items: [
      { id: 'overview', label: 'Overview', icon: IconDashboard },
      { id: 'monitor', label: 'Live monitor', icon: IconActivity },
      { id: 'users', label: 'Players', icon: IconUsers },
      { id: 'moderation', label: 'Moderation', icon: IconShield },
    ],
  },
  {
    label: 'Economy',
    items: [
      { id: 'purchases', label: 'Purchases', icon: IconShoppingBag },
      { id: 'transactions', label: 'Credit changes', icon: IconReceipt },
      { id: 'stores', label: 'Stores', icon: IconBuildingStore },
      { id: 'catalog', label: 'Item catalog', icon: IconPackage },
    ],
  },
  {
    label: 'Server',
    items: [
      { id: 'audit', label: 'Audit log', icon: IconHistory },
      { id: 'operators', label: 'Panel access', icon: IconKey },
    ],
  },
];
export const sections = groups.flatMap((group) => group.items);
export function ThemeToggle() {
  const [dark, setDark] = useState(true);
  useEffect(() => setDark(document.documentElement.classList.contains('dark')), []);
  return (
    <Button
      variant="ghost"
      size="sm"
      className="justify-start"
      onClick={() => {
        const next = !dark;
        document.documentElement.classList.toggle('dark', next);
        try {
          localStorage.setItem('nebula-theme', next ? 'dark' : 'light');
        } catch {}
        setDark(next);
      }}
    >
      {dark ? <IconSun aria-hidden /> : <IconMoon aria-hidden />}
      {dark ? 'Light mode' : 'Dark mode'}
    </Button>
  );
}
export function AppSidebar({
  view,
  navigate,
  actor,
  logout,
}: {
  view: string;
  navigate: (view: string) => void;
  actor: { id: string; role: string };
  logout: () => void;
}) {
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <Sidebar collapsible="offcanvas" variant="inset">
      <SidebarHeader>
        <a href="#overview" className="flex items-center gap-2 px-2 py-1.5 font-semibold">
          <IconPlanet aria-hidden className="size-5" />
          <span className="leading-tight">
            Nebula
            <span className="block text-xs font-normal text-muted-foreground">Server control</span>
          </span>
        </a>
      </SidebarHeader>
      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items
                  .filter((s) => s.id !== 'operators' || actor.role === 'owner')
                  .map((s) => (
                    <SidebarMenuItem key={s.id}>
                      <SidebarMenuButton
                        isActive={view === s.id}
                        onClick={() => {
                          navigate(s.id);
                          if (isMobile) setOpenMobile(false);
                        }}
                      >
                        <s.icon aria-hidden />
                        <span>{s.label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <div className="rounded-md border px-3 py-2 text-xs">
          <p className="break-all font-medium">{actor.id}</p>
          <p className="capitalize text-muted-foreground">{actor.role}</p>
        </div>
        <ThemeToggle />
        <Button variant="ghost" size="sm" className="justify-start" onClick={logout}>
          <IconLogout aria-hidden />
          Sign out
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}

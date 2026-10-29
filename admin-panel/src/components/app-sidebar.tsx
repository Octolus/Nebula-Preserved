import {
  IconDashboard,
  IconUsers,
  IconReceipt,
  IconShield,
  IconPackage,
  IconPlanet,
  IconLogout,
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
export const sections = [
  { id: 'overview', label: 'Overview', icon: IconDashboard },
  { id: 'users', label: 'Players', icon: IconUsers },
  { id: 'moderation', label: 'Moderation', icon: IconShield },
  { id: 'transactions', label: 'Credit adjustments', icon: IconReceipt },
  { id: 'catalog', label: 'Item catalog', icon: IconPackage },
  { id: 'audit', label: 'Audit log', icon: IconShield },
  { id: 'operators', label: 'Panel access', icon: IconUsers },
];
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
        <a href="/" className="flex min-h-12 items-center gap-3 px-2 font-semibold">
          <IconPlanet aria-hidden className="size-7" />
          <span>
            Nebula
            <span className="block text-xs font-normal text-muted-foreground">
              Preservation control
            </span>
          </span>
        </a>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Server management</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {sections
                .filter((s) => s.id !== 'operators' || actor.role === 'owner')
                .map((s) => (
                  <SidebarMenuItem key={s.id}>
                    <SidebarMenuButton
                      className="min-h-11"
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
      </SidebarContent>
      <SidebarFooter>
        <div className="rounded-md border p-3 text-sm">
          <p className="break-all font-medium">{actor.id}</p>
          <p className="capitalize text-muted-foreground">{actor.role}</p>
        </div>
        <Button variant="ghost" className="min-h-11 justify-start" onClick={logout}>
          <IconLogout aria-hidden />
          Sign out
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}

import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BarChart3, Boxes, ClipboardList, Inbox, LogOut } from "lucide-react";
import { useAuth } from "@/features/auth/AuthProvider";
import { isStaff } from "@/features/auth/types";
import { TapeGlyph } from "@/features/auth/LoginPage";
import { cn } from "@/shared/lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  roles?: string[];
}

const NAV: NavItem[] = [
  {
    to: "/requests",
    label: "My requests",
    icon: <Inbox className="h-[18px] w-[18px]" />,
    roles: ["client"],
  },
  {
    to: "/queue",
    label: "Queue",
    icon: <ClipboardList className="h-[18px] w-[18px]" />,
    roles: ["admin", "operator"],
  },
  {
    to: "/inventory",
    label: "Inventory",
    icon: <Boxes className="h-[18px] w-[18px]" />,
    roles: ["admin", "operator"],
  },
  {
    to: "/analytics",
    label: "Analytics",
    icon: <BarChart3 className="h-[18px] w-[18px]" />,
    roles: ["admin", "operator"],
  },
  {
    to: "/users",
    label: "Users",
    icon: <ClipboardList className="h-[18px] w-[18px]" />,
    roles: ["admin"],
  },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  // Explicit sign-out goes to a CLEAN /login. (An expired session keeps its `from` deep-link so the same
  // user returns where they were; carrying it across an intentional sign-out would drop the NEXT
  // person to sign in onto the previous user's page.)
  const signOut = () => {
    logout();
    navigate("/login", { replace: true });
  };
  const items = NAV.filter((n) => !n.roles || n.roles.includes(user.role));

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
      >
        Skip to content
      </a>

      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-screen flex-col border-r border-line bg-surface lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand">
            <TapeGlyph />
          </span>
          <span className="text-[15px] font-semibold leading-tight">
            Request
            <br />
            Desk
          </span>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-1 px-3 py-2">
          {items.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-tint text-brand-dark"
                    : "text-ink-soft hover:bg-ink/5 hover:text-ink",
                )
              }
            >
              {n.icon}
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-4">
          <p className="truncate text-sm font-medium">{user.name}</p>
          <p className="mb-3 text-xs capitalize text-ink-mute">
            {user.role}
            {isStaff(user.role) ? " · staff" : ""}
          </p>
          <button
            onClick={signOut}
            className="flex items-center gap-2 text-sm text-ink-soft hover:text-ink"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur lg:hidden">
          <div className="flex items-center justify-between px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-brand">
                <TapeGlyph />
              </span>
              Request Desk
            </span>
            <button
              onClick={signOut}
              aria-label="Sign out"
              className="rounded-lg p-2 text-ink-soft hover:bg-ink/5"
            >
              <LogOut className="h-[18px] w-[18px]" />
            </button>
          </div>
          <nav
            aria-label="Main"
            className="flex gap-1 overflow-x-auto px-3 pb-2"
          >
            {items.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  cn(
                    "flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium",
                    isActive
                      ? "bg-brand-tint text-brand-dark"
                      : "text-ink-soft",
                  )
                }
              >
                {n.icon}
                {n.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main
          id="main"
          className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-8 sm:py-9"
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}

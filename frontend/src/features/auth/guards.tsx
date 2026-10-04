import { Navigate, Outlet, useLocation } from "react-router-dom";
import { Skeleton } from "@/shared/ui/Skeleton";
import { useAuth } from "./AuthProvider";
import { homePathFor, type Role } from "./types";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-8" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

/** Client-side role gate. UX only: the API enforces the same rules and is the real boundary. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth();
  if (!user) return null;
  if (!roles.includes(user.role)) return <Navigate to={homePathFor(user.role)} replace />;
  return <Outlet />;
}

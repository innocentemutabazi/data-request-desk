import { Navigate, Route, Routes } from "react-router-dom";
import { AnalyticsPage } from "@/features/analytics";
import { useAuth } from "@/features/auth/AuthProvider";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/LoginPage";
import { AdminUsersPage } from "@/features/auth/AdminUsersPage";
import { homePathFor } from "@/features/auth/types";
import { InventoryPage } from "@/features/inventory";
import {
  ClientDashboard,
  OperatorDashboard,
  RequestDetailPage,
} from "@/features/requests";
import { AppShell } from "./AppShell";

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? homePathFor(user.role) : "/login"} replace />;
}

function NotFound() {
  return (
    <div className="py-24 text-center">
      <p className="text-5xl font-semibold text-ink-mute">404</p>
      <p className="mt-2 text-ink-soft">That page doesn’t exist.</p>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route element={<RequireRole roles={["client"]} />}>
            <Route path="/requests" element={<ClientDashboard />} />
          </Route>
          <Route element={<RequireRole roles={["admin", "operator"]} />}>
            <Route path="/queue" element={<OperatorDashboard />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
          </Route>
          <Route element={<RequireRole roles={["admin"]} />}>
            <Route path="/users" element={<AdminUsersPage />} />
          </Route>
          <Route path="/requests/:id" element={<RequestDetailPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { setUnauthorizedHandler, tokenStore } from "@/shared/lib/api";
import { useToast } from "@/shared/toast/ToastProvider";
import * as authApi from "./api";
import type { User } from "./types";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: User | null;
  status: Status;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>(() => (tokenStore.get() ? "loading" : "anonymous"));
  const queryClient = useQueryClient();
  const toast = useToast();

  const clearSession = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setStatus("anonymous");
    queryClient.clear(); // never let one user's cached data leak into the next session
  }, [queryClient]);

  // Restore the session after a page reload.
  useEffect(() => {
    if (!tokenStore.get()) return;
    let cancelled = false;
    authApi
      .fetchMe()
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setStatus("authenticated");
      })
      .catch(() => !cancelled && clearSession());
    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  // Any 401 on an authenticated call = expired/revoked token.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      toast.info("Session ended", "Please sign in again.");
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSession, toast]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await authApi.login(email, password);
      queryClient.clear();
      tokenStore.set(res.access_token);
      setUser(res.user);
      setStatus("authenticated");
      return res.user;
    },
    [queryClient],
  );

  const value = useMemo(() => ({ user, status, login, logout: clearSession }), [user, status, login, clearSession]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** For screens that only render when signed in. */
export function useCurrentUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useCurrentUser called without a signed-in user");
  return user;
}

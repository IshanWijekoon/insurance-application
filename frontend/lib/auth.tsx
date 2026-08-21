"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, post, setToken } from "./api";
import type { MeResponse, Role, User } from "./types";

type AuthCtx = {
  user: User | null;
  me: MeResponse | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (payload: { email: string; password: string; full_name: string; phone?: string }) => Promise<User>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

function homeFor(role: Role) {
  if (role === "AGENT") return "/agent";
  if (role === "ADMIN") return "/admin";
  return "/client";
}

function loginFor(role: Role) {
  if (role === "AGENT" || role === "ADMIN") return "/login/agent";
  return "/login";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api<MeResponse>("/api/v1/auth/me")
      .then(setMe)
      .catch(() => {
        clearToken();
        setMe(null);
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const res = await post<{ access_token: string; user: User }>("/api/v1/auth/login", { email, password });
    setToken(res.access_token);
    const profile = await api<MeResponse>("/api/v1/auth/me");
    setMe(profile);
    return res.user;
  }

  async function register(payload: { email: string; password: string; full_name: string; phone?: string }) {
    const res = await post<{ access_token: string; user: User }>("/api/v1/auth/register", payload);
    setToken(res.access_token);
    const profile = await api<MeResponse>("/api/v1/auth/me");
    setMe(profile);
    return res.user;
  }

  async function logout() {
    try {
      await post("/api/v1/auth/logout");
    } finally {
      clearToken();
      setMe(null);
    }
  }

  return (
    <Ctx.Provider value={{ user: me?.user ?? null, me, loading, login, register, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function useRequireRole(roles: Role[]) {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!user) {
      const staffOnly = roles.some((r) => r === "AGENT" || r === "ADMIN") && !roles.includes("CUSTOMER");
      router.replace(staffOnly ? "/login/agent" : "/login");
      return;
    }
    if (!roles.includes(user.role)) router.replace(homeFor(user.role));
  }, [user, loading, router, roles]);
  return { user, loading };
}

export { homeFor, loginFor };

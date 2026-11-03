import { useEffect, useSyncExternalStore } from "react";

import * as api from "../lib/api";
import { authFailureMessage, isAuthRejected } from "../lib/auth-feedback";
import type { PlatformUser } from "../types";

type AuthStatus = "checking" | "authenticated" | "anonymous";

type AuthSnapshot = {
  status: AuthStatus;
  user: PlatformUser | null;
  error: string | null;
};

let snapshot: AuthSnapshot = {
  status: api.hasRefreshToken() ? "checking" : "anonymous",
  user: null,
  error: null
};

let bootstrapped = false;
let authActionRevision = 0;
const listeners = new Set<() => void>();

function emit(next: AuthSnapshot): void {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): AuthSnapshot {
  return snapshot;
}

function authErrorMessage(error: unknown, fallback: string): string {
  return authFailureMessage(error, fallback);
}

async function bootstrap(): Promise<void> {
  if (bootstrapped) {
    return;
  }
  bootstrapped = true;
  if (!api.hasRefreshToken()) {
    emit({ status: "anonymous", user: null, error: null });
    return;
  }

  emit({ ...snapshot, status: "checking", error: null });
  const action = authActionRevision;
  const revision = api.getAuthSessionRevision();
  try {
    const user = await api.bootstrapAuth();
    if (action !== authActionRevision || revision !== api.getAuthSessionRevision()) return;
    emit(user ? { status: "authenticated", user, error: null } : { status: "anonymous", user: null, error: null });
  } catch (error) {
    if (action !== authActionRevision || (revision !== api.getAuthSessionRevision() && api.hasRefreshToken())) return;
    if (isAuthRejected(error)) api.clearAuthTokens();
    emit({ status: "anonymous", user: null, error: isAuthRejected(error) ? "登录已过期，请重新登录。" : authErrorMessage(error, "暂时无法验证登录状态，请稍后重试。") });
  }
}

async function login(credentials: api.AuthCredentials): Promise<void> {
  const action = ++authActionRevision;
  emit({ ...snapshot, error: null });
  try {
    const payload = await api.login(credentials);
    if (action !== authActionRevision) return;
    emit({ status: "authenticated", user: payload.user, error: null });
  } catch (error) {
    const message = authErrorMessage(error, "登录未完成，请稍后重试。");
    if (action === authActionRevision) emit({ status: "anonymous", user: null, error: message });
    throw new Error(message);
  }
}

async function register(credentials: api.AuthCredentials): Promise<void> {
  const action = ++authActionRevision;
  emit({ ...snapshot, error: null });
  try {
    const payload = await api.register(credentials);
    if (action !== authActionRevision) return;
    emit({ status: "authenticated", user: payload.user, error: null });
  } catch (error) {
    const message = authErrorMessage(error, "注册未完成，请稍后重试。");
    if (action === authActionRevision) emit({ status: "anonymous", user: null, error: message });
    throw new Error(message);
  }
}

async function logout(): Promise<void> {
  const action = ++authActionRevision;
  try {
    await api.logout();
  } finally {
    if (action === authActionRevision) emit({ status: "anonymous", user: null, error: null });
  }
}

export function useAuth() {
  const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    void bootstrap();
  }, []);

  return {
    ...current,
    isAuthenticated: current.status === "authenticated",
    isChecking: current.status === "checking",
    login,
    register,
    logout
  };
}

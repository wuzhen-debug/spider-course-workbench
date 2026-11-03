/** Binding errors stay in the active panel; never stringify request bodies or secrets. */
export function loginErrorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== "object") return undefined;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === "number" ? response.status : undefined;
}

export function loginErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const response = (error as { response?: { data?: { detail?: unknown } }; code?: string }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const text = (detail as { message?: unknown }).message;
      if (typeof text === "string" && text.trim()) return text.trim();
    }
    if (loginErrorStatus(error) === 401) return "本机工作台登录已过期，请重新登录后再绑定账号。";
    if ((error as { code?: string }).code === "ERR_NETWORK") return "无法连接本机登录服务，请检查后台是否运行后重试。";
  }
  return fallback;
}

/** One outstanding poll at a time. Cancellation also ignores any late response. */
export function pollLoginSequentially<T>(options: {
  load: () => Promise<T>;
  onResult: (result: T) => boolean;
  onError: (error: unknown, failures: number) => boolean;
  schedule?: (callback: () => void, delay: number) => number;
  unschedule?: (timer: number) => void;
}) {
  const schedule = options.schedule ?? ((callback, delay) => window.setTimeout(callback, delay));
  const unschedule = options.unschedule ?? ((timer) => window.clearTimeout(timer));
  let stopped = false;
  let failures = 0;
  let timer: number | null = null;
  function stop() {
    stopped = true;
    if (timer !== null) unschedule(timer);
    timer = null;
  }
  async function next() {
    timer = null;
    try {
      const result = await options.load();
      if (stopped) return;
      failures = 0;
      if (!options.onResult(result)) return stop();
    } catch (error) {
      if (stopped) return;
      failures += 1;
      if (!options.onError(error, failures)) return stop();
    }
    if (!stopped) timer = schedule(() => { void next(); }, Math.min(2000 * 2 ** failures, 15000));
  }
  timer = schedule(() => { void next(); }, 2000);
  return stop;
}

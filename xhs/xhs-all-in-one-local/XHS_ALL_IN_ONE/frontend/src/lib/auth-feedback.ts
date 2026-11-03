type AuthFailure = {
  code?: string;
  isAxiosError?: boolean;
  request?: unknown;
  response?: { status?: number; data?: { detail?: unknown } };
};

export function authFailureMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") return fallback;
  const failure = error as AuthFailure;
  const status = failure.response?.status;
  const detail = failure.response?.data?.detail;
  if (!failure.response) {
    if (!failure.isAxiosError && !failure.request && !failure.code) return fallback;
    if (["ECONNABORTED", "ETIMEDOUT"].includes(failure.code ?? "")) {
      return "连接本机服务超时，请确认 Spider 服务已启动后重试。";
    }
    return "无法连接本机服务，请确认 Spider 服务已启动后重试。";
  }
  if (status === 401) return "账号不存在或密码错误，请检查后重试。";
  if (detail === "Username already exists") return "该平台账号已存在，请直接登录或换一个账号。";
  if (status !== undefined && status >= 500) return "本机平台服务暂时异常，请稍后重试；账号和现有资料不会因此删除。";
  if (status === 422) return "提交的账号或密码格式不符合要求，请检查后重试。";
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

export function isAuthRejected(error: unknown): boolean {
  const status = (error as AuthFailure | undefined)?.response?.status;
  return status === 401 || status === 403;
}

export function isCredentialEndpoint(url: string | undefined): boolean {
  const path = (url ?? "").split("?")[0].replace(/\/$/, "");
  return /\/(?:auth)\/(?:login|register|refresh|logout)$/.test(path);
}

export type AuthFormFields = { username: string; password: string; confirmPassword: string };

export function authFormFields(data: Pick<FormData, "get"> | null, fallback: AuthFormFields): AuthFormFields {
  const value = (name: keyof AuthFormFields) => {
    const field = data?.get(name);
    return typeof field === "string" ? field : fallback[name];
  };
  return { username: value("username"), password: value("password"), confirmPassword: value("confirmPassword") };
}

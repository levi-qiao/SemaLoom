export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type StudioSession = {
  authenticated?: boolean;
  tenant: string;
  subject: string;
  roles: string[];
};

export function apiHeaders(): Record<string, string> {
  const csrf = document.cookie
    .split("; ")
    .find((item) => item.startsWith("semaloom_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
  return {
    "Content-Type": "application/json",
    ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
  };
}

export function hasRole(session: StudioSession | null | undefined, ...roles: string[]) {
  const current = session?.roles ?? [];
  return roles.some((role) => current.includes(role));
}

export function errorDetail(cause: unknown) {
  if (cause instanceof ApiError) return cause.detail;
  if (cause instanceof Error) return cause.message;
  return "UNKNOWN_ERROR";
}

export async function ensureSession(): Promise<StudioSession> {
  const current = await fetch("/v0.1/studio/session/bootstrap").then(checkedJson);
  if (current.authenticated) return current as StudioSession;
  return checkedJson(
    await fetch("/v0.1/studio/session/demo", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ persona: "studio-admin" }),
    }),
  ) as Promise<StudioSession>;
}

export async function checkedJson<T = any>(response: Response): Promise<T> {
  let payload: { detail?: unknown } | null = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const diagnostics = (payload?.detail as { diagnostics?: { path: string; message: string }[] } | undefined)?.diagnostics;
    if (Array.isArray(diagnostics) && diagnostics.length) {
      throw new ApiError(
        response.status,
        diagnostics
          .slice(0, 3)
          .map((item) => `${item.path}: ${item.message}`)
          .join("；"),
      );
    }
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, detail);
  }
  return payload as T;
}

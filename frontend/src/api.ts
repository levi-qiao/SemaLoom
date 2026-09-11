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

export async function ensureSession() {
  const current = await fetch("/v0.1/studio/session/bootstrap").then(checkedJson);
  if (current.authenticated) return current;
  return checkedJson(
    await fetch("/v0.1/studio/session/demo", {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ persona: "studio-admin" }),
    }),
  );
}

export async function checkedJson(response: Response) {
  const payload = await response.json();
  if (!response.ok) {
    const diagnostics = payload?.detail?.diagnostics;
    if (Array.isArray(diagnostics) && diagnostics.length) {
      throw new Error(
        diagnostics
          .slice(0, 3)
          .map((item) => `${item.path}: ${item.message}`)
          .join("；"),
      );
    }
    throw new Error(
      typeof payload?.detail === "string"
        ? payload.detail
        : `${response.status} ${response.statusText}`,
    );
  }
  return payload;
}

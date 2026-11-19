// Thin API client. Distinguishes "server said no" (ApiError) from "could not reach server" (OfflineError),
// so the POS knows when to fall back to the offline queue.

export class ApiError extends Error {
  constructor(public status: number, public data: any) {
    super(data?.detail || `HTTP ${status}`);
  }
}
export class OfflineError extends Error {}

const TOKEN_KEY = "pos.token";
const BRANCH_KEY = "pos.branch";

export const auth = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set token(v: string | null) { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); },
  get branch() { return localStorage.getItem(BRANCH_KEY); },
  set branch(v: string | null) { v ? localStorage.setItem(BRANCH_KEY, v) : localStorage.removeItem(BRANCH_KEY); },
};

// `branch`: omit to use the till's branch, pass null for "all branches I can see", or an id.
export async function api<T = any>(path: string,
  opts: { method?: string; body?: unknown; branch?: string | null } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const branch = opts.branch === undefined ? auth.branch : opts.branch;
  if (branch) headers["X-Branch-ID"] = branch;
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new OfflineError("Server unreachable");
  }
  // A proxy with the backend down answers 502/503/504: treat that as offline too.
  if ([502, 503, 504].includes(res.status)) throw new OfflineError(`Gateway ${res.status}`);
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/** Multipart upload (photos). The browser sets the multipart Content-Type with its boundary itself. */
export async function apiForm<T = any>(path: string, form: FormData, method = "PATCH", branch?: string | null): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  if (branch) headers["X-Branch-ID"] = branch;
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: form });
  } catch {
    throw new OfflineError("Server unreachable");
  }
  if ([502, 503, 504].includes(res.status)) throw new OfflineError(`Gateway ${res.status}`);
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export async function login(username: string, password: string) {
  const data = await api<{ access: string }>("/auth/token/", { body: { username, password } });
  auth.token = data.access;
}

export const money = (v: number | string) =>
  Number(v).toLocaleString("en-MW", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Whole currency units for headline tiles (MWK amounts rarely need tambala at a glance). */
export const whole = (v: number | string) => Math.round(Number(v)).toLocaleString("en-MW");

/** Download a file from the API (signed in) and hand it to the browser to save. */
export async function apiDownload(path: string, filename: string) {
  const headers: Record<string, string> = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(`/api${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

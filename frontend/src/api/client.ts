/** Same-origin V3 API — never default to ERP V1 port 8000. */
const DEFAULT_BASE = "/api/v1";

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  return DEFAULT_BASE;
}

export type HealthPayload = {
  status: string;
  service: string;
  version: string;
  environment: string;
};

export type ReadyPayload = {
  status: string;
  database: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
};

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`);
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      // keep defaults
    }
    throw new ApiClientError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthPayload> {
  return request<HealthPayload>("/health");
}

export function fetchReady(): Promise<ReadyPayload> {
  return request<ReadyPayload>("/ready");
}

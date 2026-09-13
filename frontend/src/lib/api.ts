export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `요청을 처리하지 못했습니다 (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown; message?: unknown };
      message = readableError(body.detail ?? body.message) ?? message;
    } catch {
      // Non-JSON upstream errors use the status-based message.
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

function readableError(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    const messages = value.map((item) => {
      if (!item || typeof item !== 'object') return String(item);
      const error = item as { loc?: unknown[]; msg?: unknown };
      const field = Array.isArray(error.loc) ? error.loc.filter((part) => part !== 'body').join('.') : '';
      return `${field ? `${field}: ` : ''}${String(error.msg ?? '입력값을 확인하세요.')}`;
    });
    return messages.join(' · ');
  }
  if (value && typeof value === 'object') return JSON.stringify(value);
  return value === null || value === undefined ? null : String(value);
}

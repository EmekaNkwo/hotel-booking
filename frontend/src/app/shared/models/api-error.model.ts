/** Normalized client-side representation of any backend HTTP error.
 *
 * A0 views consistently return `{detail: string}` for hand-written errors
 * (400/401/403/404/409/422); DRF's default validation path (unused by the
 * auth endpoints today, but used elsewhere) returns `{field: [messages]}`.
 * Both are folded into `message` here so callers never need to know which
 * shape the backend used.
 */
export interface ApiError {
  status: number;
  message: string;
  /** The raw response body, for callers that need field-level detail. */
  raw: unknown;
}

export function toApiError(status: number, body: unknown): ApiError {
  return { status, message: extractMessage(status, body), raw: body };
}

/** Builds an `ApiError` from whatever a failed `HttpClient` call rejects
 * with (an `HttpErrorResponse`-shaped object, or a network-level failure
 * with no `status`/`error` at all). */
export function fromHttpError(err: unknown): ApiError {
  if (err && typeof err === 'object' && 'status' in err) {
    const httpErr = err as { status: number; error: unknown };
    return toApiError(httpErr.status, httpErr.error);
  }
  return toApiError(0, null);
}

function extractMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    if (typeof record['detail'] === 'string') {
      return record['detail'];
    }
    // DRF field-error shape: {field: ["msg", ...], ...}
    const fieldMessages = Object.values(record)
      .flat()
      .filter((v): v is string => typeof v === 'string');
    if (fieldMessages.length > 0) {
      return fieldMessages.join(' ');
    }
  }
  return fallbackMessage(status);
}

function fallbackMessage(status: number): string {
  switch (status) {
    case 400:
      return 'The request could not be processed as sent.';
    case 401:
      return 'Your session has expired. Please log in again.';
    case 403:
      return 'You do not have permission to do that.';
    case 404:
      return 'The requested resource was not found.';
    case 409:
      return 'This could not be completed because of a conflicting state change.';
    case 429:
      return 'Too many requests. Please wait a moment and try again.';
    case 0:
      return 'Could not reach the server. Check your connection.';
    default:
      if (status >= 500) {
        return 'The server encountered an error. Please try again.';
      }
      return 'An unexpected error occurred.';
  }
}

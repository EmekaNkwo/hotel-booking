/** R0.8: the backend's standard DRF `PageNumberPagination` envelope,
 * returned by every list endpoint since the backend's remediation pass
 * made pagination real (see `apps.shared.api.pagination.paginate_list`).
 * API services unwrap this to a plain array at the HTTP boundary — no
 * Store or component needs to know a page exists; that keeps every
 * feature's "array in, array out" Store contract unchanged. */
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

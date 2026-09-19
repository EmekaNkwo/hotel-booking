/** Reads one cookie's value by name from `document.cookie`. Returns null
 * when absent — the caller decides what that means (e.g. no CSRF cookie yet
 * means no session has ever hit the backend, so nothing to send). */
export function readCookie(name: string): string | null {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`));
  if (!match) {
    return null;
  }
  return decodeURIComponent(match.slice(name.length + 1));
}

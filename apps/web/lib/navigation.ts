/** Full-page navigation that discards in-memory state, used when the identity behind the session cookie changes. */
export function hardNavigate(path: string): void {
  window.location.replace(path);
}

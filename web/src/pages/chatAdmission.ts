/** Keep retryable composer state until the server has accepted the turn. */
export function handleChatAdmission(
  response: Pick<Response, "ok" | "status">,
  accept: () => void,
  reject: (message: string) => void,
  detail?: string,
): boolean {
  if (!response.ok) {
    // A 413 carries the server's own reason (what was too large and what to do about it).
    reject(response.status === 409
      ? "Your coach is already responding in this mode. Your draft and attachments are ready to retry."
      : response.status === 413 && detail
        ? detail
        : "Your message could not be accepted. Please try again.");
    return false;
  }
  accept();
  return true;
}

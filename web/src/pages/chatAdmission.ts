/** Keep retryable composer state until the server has accepted the turn. */
export function handleChatAdmission(
  response: Pick<Response, "ok" | "status">,
  accept: () => void,
  reject: (message: string) => void,
): boolean {
  if (!response.ok) {
    reject(response.status === 409
      ? "Your coach is already responding in this mode. Your draft and attachments are ready to retry."
      : "Your message could not be accepted. Please try again.");
    return false;
  }
  accept();
  return true;
}

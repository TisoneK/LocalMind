/**
 * Crash reports — what a recovery card copies when the user asks for details.
 *
 * A crash report must answer "what broke, where, in what" without the user
 * typing anything: the error message, the JS stack, React's component stack
 * (which names the UI region that died), and the environment. Plain text,
 * paste-ready for a bug report.
 */

export function buildCrashReport(
  error: Error,
  componentStack?: string | null,
  when: Date = new Date(),
): string {
  const lines = [
    `LocalMind crash report — ${when.toISOString()}`,
    '',
    `${error.name}: ${error.message}`,
  ];
  if (error.stack) lines.push('', 'Stack:', error.stack);
  if (componentStack) lines.push('', 'Component stack:', componentStack.trim());
  if (typeof navigator !== 'undefined' && navigator.userAgent) {
    lines.push('', `User agent: ${navigator.userAgent}`);
  }
  return lines.join('\n');
}

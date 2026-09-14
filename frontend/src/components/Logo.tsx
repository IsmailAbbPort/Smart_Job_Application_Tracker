// Target (matching) with an AI sparkle. The square follows the text colour so the
// mark inverts cleanly between the light and dark themes.
export function Logo() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="var(--text)" />
      <circle cx="12.8" cy="15.2" r="6.6" fill="none" stroke="var(--panel)" strokeWidth="2.1" />
      <circle cx="12.8" cy="15.2" r="2.6" fill="var(--logo-mark)" />
      <path
        d="M21 3.8c.35 1.9 1.1 2.65 3 3-1.9.35-2.65 1.1-3 3-.35-1.9-1.1-2.65-3-3 1.9-.35 2.65-1.1 3-3z"
        fill="var(--logo-mark)"
      />
    </svg>
  );
}

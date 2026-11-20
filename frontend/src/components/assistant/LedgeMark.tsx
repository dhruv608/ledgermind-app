// Ledge, the assistant's mark: a speech bubble with two ledger lines, the second one ticked. Drawn in currentColor so
// it takes the colour of where it sits (white on the teal button, teal in a header).
export function LedgeMark({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path d="M5 4h14a2.5 2.5 0 0 1 2.5 2.5v8A2.5 2.5 0 0 1 19 17h-7.5L7 20.5V17H5a2.5 2.5 0 0 1-2.5-2.5v-8A2.5 2.5 0 0 1 5 4z"
            stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M7 8.5h10M7 12.5h4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M13.5 12.6l1.6 1.6 3-3.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

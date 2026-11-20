// The app's text levels, so every screen reads in the same order: page title, section title, card title, body text,
// small grey detail, and the small capital labels over a field. Use these instead of picking sizes by hand.
export const text = {
  page: "text-lg font-semibold tracking-tight text-slate-900",
  section: "text-[15px] font-semibold text-slate-900",
  card: "text-sm font-semibold leading-snug text-slate-900",
  body: "text-[13px] leading-relaxed text-slate-700",
  meta: "text-xs text-slate-500",
  label: "text-[10.5px] font-semibold uppercase tracking-wide text-slate-400",
};

// Gaps: between sections of a page, and inside a card
export const gap = {
  sections: "space-y-5",
  card: "px-4 py-3.5",
};

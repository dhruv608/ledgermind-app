// The boxes of the VAT return (HMRC form VAT100, VAT Notice 700/12 section 3): points say "Box 1", "Box 4"; the screen
// names each the first time it appears in a text, for readers who do not know the numbers
const BOXES: Record<string, string> = {
  "1": "VAT on sales",
  "2": "VAT on EU acquisitions",
  "3": "total VAT due",
  "4": "VAT reclaimed on purchases",
  "5": "net VAT to pay or reclaim",
  "6": "total sales before VAT",
  "7": "total purchases before VAT",
  "8": "goods supplied to the EU",
  "9": "goods acquired from the EU",
};

/** 'Box 1 differs ... Box 1 and Box 4' -> 'Box 1 (VAT on sales) differs ... Box 1 and Box 4 (VAT reclaimed on purchases)'.
 *  A box already followed by its name in brackets is left as it is. */
export function nameVatBoxes(text: string): string {
  const named = new Set<string>();
  return (text || "").replace(/\b(Box|box)\s+([1-9])\b(?!\s*\()/g, (whole, word: string, n: string) => {
    if (named.has(n)) return whole;
    named.add(n);
    return `${word} ${n} (${BOXES[n]})`;
  });
}

/**
 * takeWords — a take's words placed on its timeline, from the transcript's segments.
 *
 * joe knows when each segment of a take began and ended, not when each word did:
 * a segment's words share its span evenly, in order, which is close for the short
 * stretches a segment is cut into and is drawn as no more than that. A struck word
 * keeps its place, marked struck; a segment without times or words places nothing.
 *
 * @param {object} entry - a take from the transcript: `{ segments: [{ words, struck, start, end }] }`
 * @returns {Array<{ text: string, start: number, end: number, struck: boolean }>}
 */
export function takeWords(entry) {
  const placed = [];
  for (const segment of entry?.segments || []) {
    const words = segment.words || [];
    if (!words.length || segment.start == null || segment.end == null || segment.end <= segment.start) continue;
    const span = (segment.end - segment.start) / words.length;
    words.forEach((text, i) => placed.push({
      text,
      start: segment.start + i * span,
      end: segment.start + (i + 1) * span,
      struck: (segment.struck || []).includes(i),
    }));
  }
  return placed;
}

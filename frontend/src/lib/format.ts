import type { JsonValue } from './types';

/** Compact cell text: integers as is, floats with 4 significant digits (scientific when tiny/huge). */
export function formatCell(v: JsonValue): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v);
    const a = Math.abs(v);
    if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(2);
    return String(Number(v.toPrecision(4)));
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

/** Sort comparator for table cells: nulls last in both directions, numbers numerically, everything else as text. */
export function compareCells(a: JsonValue, b: JsonValue, dir: 'asc' | 'desc' = 'asc'): number {
  const an = a === null || a === undefined;
  const bn = b === null || b === undefined;
  if (an || bn) return an === bn ? 0 : an ? 1 : -1;
  const sign = dir === 'asc' ? 1 : -1;
  if (typeof a === 'number' && typeof b === 'number') return sign * (a - b);
  return sign * String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

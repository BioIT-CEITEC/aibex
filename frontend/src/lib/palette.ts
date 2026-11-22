// One palette for the whole app (T53, P5.4): plot colours and chart chrome for the light and the dark theme. The
// theme comes from the spec (`theme.dark`), so a dark dashboard is an undoable spec change like any other.
//
// Categorical slots: an 8-hue order validated for colour-vision deficiency in both modes (adjacent CVD ΔE ≥ 8,
// normal-vision ΔE ≥ 15; checked with the dataviz validator against white and the dark card surface). The dark column
// is the same hues stepped for the dark surface, not a different palette. Slots are assigned in order of first
// appearance and never cycled into generated hues.

export type ThemeMode = 'light' | 'dark';

/** Categorical series colours, slot order matters (CVD-safe adjacency). */
export const CATEGORICAL: Record<ThemeMode, readonly string[]> = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9', '#e66767'],
};

type Scale = [number, string][];

/**
 * Diverging blue ↔ red with a neutral grey midpoint (never a hue at 0). In the dark theme the midpoint is a dark grey
 * close to the surface and the poles get brighter, so "far from 0" always reads as "more ink".
 */
export const DIVERGING: Record<ThemeMode, Scale> = {
  light: [
    [0, '#1c5cab'],
    [0.25, '#86b6ef'],
    [0.5, '#f0efec'],
    [0.75, '#f0a19a'],
    [1, '#c0302f'],
  ],
  dark: [
    [0, '#6da7ec'],
    [0.25, '#2e5f9e'],
    [0.5, '#383835'],
    [0.75, '#9e3a39'],
    [1, '#ef7a79'],
  ],
};

/** Sequential single hue (blue) for a continuous field: near zero recedes toward the surface. */
export const SEQUENTIAL: Record<ThemeMode, Scale> = {
  light: [
    [0, '#eef4fc'],
    [0.5, '#5598e7'],
    [1, '#0d366b'],
  ],
  dark: [
    [0, '#1d2a3d'],
    [0.5, '#256abf'],
    [1, '#b7d3f6'],
  ],
};

/**
 * Sequential scale for *marks* (scatter points coloured by a number): the lightest/darkest step still stands out from
 * the surface, unlike the heatmap scale whose zero end may fade into it.
 */
export const SEQUENTIAL_MARKS: Record<ThemeMode, Scale> = {
  light: [
    [0, '#86b6ef'],
    [0.5, '#256abf'],
    [1, '#0d366b'],
  ],
  dark: [
    [0, '#184f95'],
    [0.5, '#3987e5'],
    [1, '#cde2fb'],
  ],
};

/**
 * Diverging scale for *marks* coloured by a signed number (e.g. editing Δ): same blue ↔ red poles, but the grey
 * midpoint stays visible against the surface, so points near 0 do not disappear.
 */
export const DIVERGING_MARKS: Record<ThemeMode, Scale> = {
  light: [
    [0, '#1c5cab'],
    [0.5, '#b5b4ad'],
    [1, '#c0302f'],
  ],
  dark: [
    [0, '#6da7ec'],
    [0.5, '#6b6a66'],
    [1, '#ef7a79'],
  ],
};

/** Chart chrome: text ink, axis lines, grid, label boxes, selection ring. */
export interface Chrome {
  ink: string;
  inkSecondary: string;
  muted: string;
  grid: string;
  axis: string;
  /** background of label annotations so they stay readable over points */
  labelBg: string;
  /** thin ring around overlapping markers and between band segments: the surface colour */
  ring: string;
  /** outline of selected points / rows */
  selected: string;
}

export const CHROME: Record<ThemeMode, Chrome> = {
  light: {
    ink: '#0b0b0b',
    inkSecondary: '#52514e',
    muted: '#898781',
    grid: '#e1e0d9',
    axis: '#c3c2b7',
    labelBg: 'rgba(255,255,255,0.8)',
    ring: '#ffffff',
    selected: '#0b0b0b',
  },
  dark: {
    ink: '#f0efec',
    inkSecondary: '#c3c2b7',
    muted: '#898781',
    grid: '#2c2c2a',
    axis: '#4a4a46',
    labelBg: 'rgba(23,23,23,0.8)',
    ring: '#171717',
    selected: '#f0efec',
  },
};

/** Plotly layout keys shared by every figure: transparent background (the card shows through), themed ink and grid. */
export function plotlyChrome(mode: ThemeMode): Record<string, unknown> {
  const c = CHROME[mode];
  const axis = { gridcolor: c.grid, linecolor: c.axis, zerolinecolor: c.axis, tickcolor: c.axis };
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { size: 11, color: c.inkSecondary },
    xaxis: axis,
    yaxis: axis,
    legend: { font: { color: c.inkSecondary } },
    hoverlabel: { bgcolor: mode === 'dark' ? '#262626' : '#ffffff', bordercolor: c.axis, font: { color: c.ink } },
    colorway: [...CATEGORICAL[mode]],
  };
}

export function modeOf(theme: { dark?: boolean } | null | undefined): ThemeMode {
  return theme?.dark ? 'dark' : 'light';
}
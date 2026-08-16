/**
 * Categorical chart palette — validated slot order (CVD-safe for adjacent
 * series in both modes); dark values are the same hues re-stepped for the
 * dark surface, not an automatic flip. Assign slots in fixed order, never
 * cycled; series beyond the slots fold into "Other".
 */
export const CHART_SERIES: readonly { light: string; dark: string }[] = [
  { light: "#2a78d6", dark: "#3987e5" }, // blue
  { light: "#eb6834", dark: "#d95926" }, // orange
  { light: "#1baf7a", dark: "#199e70" }, // aqua
  { light: "#eda100", dark: "#c98500" }, // yellow
];

/** CSS-safe identifier for a metric name (e.g. "recall@5" -> "recall_5"). */
export function metricSlug(name: string): string {
  return name.replace(/[^a-zA-Z0-9_-]/g, "_");
}

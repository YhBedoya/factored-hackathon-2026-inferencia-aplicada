// R4 / D13: every number on the analytics page is formatted here, never shown
// as a raw float. Pure functions over primitives, no Intl, so ES and PT render
// identically.

const DASH = "—";

/** The only money formatter the analytics page uses (D13); cents, like `US$ 0.08`. */
export function formatUsd(usd: number | null, digits = 2): string {
	return usd === null ? DASH : `US$ ${usd.toFixed(digits)}`;
}

/** A money axis tick; the axis title carries the unit, so `0.25`. */
export function formatUsdTick(usd: number): string {
	return usd.toFixed(2);
}

/** A 0..1 rate as `12.3%`. */
export function formatPercent(rate: number | null): string {
	return rate === null ? DASH : `${(rate * 100).toFixed(1)}%`;
}

export function formatRatio(num: number, den: number): string {
	return `${num}/${den}`;
}

export function formatAvg(value: number | null, digits = 1): string {
	return value === null ? DASH : value.toFixed(digits);
}

/** Whole seconds as `m:ss`. */
export function formatSeconds(s: number | null): string {
	if (s === null) {
		return DASH;
	}
	const total = Math.round(s);
	const minutes = Math.floor(total / 60);
	const seconds = total % 60;
	return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

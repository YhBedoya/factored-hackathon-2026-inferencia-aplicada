import type { CSSProperties } from "react";

// The banking home's background (brand.md "Visual identity": stars outside
// the chat area only; the Cardy panel paints its own opaque background).
// CSS-only, like `StarryBackground`: each layer is one repeating tile of
// `radial-gradient` stars, drawn one tile larger than the viewport and
// shifted by exactly one tile per cycle (`star-drift` in `index.css`), so the
// loop never jumps. The nearest layer drifts ~10 px/s (about 10 s per
// 100 px), the farther, larger tiles ~7 and ~5 px/s for depth;
// `star-twinkle` fades each layer's opacity on its own phase.
// Product decision: this keeps moving under `prefers-reduced-motion` too.

type Layer = {
	width: number;
	height: number;
	count: number;
	seed: number;
	gold: number;
	drift: number;
	twinkle: number;
	delay: number;
};

const LAYERS: Layer[] = [
	{
		width: 360,
		height: 240,
		count: 9,
		seed: 7,
		gold: 0,
		drift: 36,
		twinkle: 7,
		delay: 0,
	},
	{
		width: 520,
		height: 360,
		count: 10,
		seed: 23,
		gold: 2,
		drift: 75,
		twinkle: 9,
		delay: -3,
	},
	{
		width: 720,
		height: 480,
		count: 8,
		seed: 41,
		gold: 2,
		drift: 144,
		twinkle: 6,
		delay: -5,
	},
];

// A tiny deterministic PRNG, so the stars sit in the same place every render.
function random(seed: number) {
	let state = seed;
	return () => {
		state = (state * 16807) % 2147483647;
		return state / 2147483647;
	};
}

function stars({ width, height, count, seed, gold }: Layer): string {
	const next = random(seed);
	return Array.from({ length: count }, (_, i) => {
		const x = Math.round(next() * width);
		const y = Math.round(next() * height);
		const size = next() < 0.3 ? 1.5 : 1;
		const alpha = (0.45 + next() * 0.5).toFixed(2);
		const color =
			i < gold ? `rgba(245,198,107,${alpha})` : `rgba(255,255,255,${alpha})`;
		return `radial-gradient(${size}px ${size}px at ${x}px ${y}px, ${color}, transparent)`;
	}).join(", ");
}

function layerStyle(layer: Layer): CSSProperties {
	return {
		top: -layer.height,
		left: -layer.width,
		backgroundImage: stars(layer),
		backgroundSize: `${layer.width}px ${layer.height}px`,
		backgroundRepeat: "repeat",
		animation: `star-drift ${layer.drift}s linear infinite, star-twinkle ${layer.twinkle}s ease-in-out ${layer.delay}s infinite`,
		"--tile-w": `${layer.width}px`,
		"--tile-h": `${layer.height}px`,
	} as CSSProperties;
}

export function DriftStarfield() {
	return (
		<div
			aria-hidden="true"
			data-testid="drift-starfield"
			className="pointer-events-none fixed inset-0 z-0 overflow-hidden bg-bg"
		>
			{LAYERS.map((layer) => (
				<div
					key={layer.seed}
					className="absolute right-0 bottom-0 will-change-transform"
					style={layerStyle(layer)}
				/>
			))}
		</div>
	);
}

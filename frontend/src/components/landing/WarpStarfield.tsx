import { useEffect, useRef } from "react";

// Landing-only "flying through space" starfield: stars sit in 3D, move toward
// the viewer and are projected by dividing by depth, so they spread from the
// centre and grow as they approach. Decorative, so it's aria-hidden and
// ignores the pointer. It paints behind the landing sections (-z-10 inside
// AppShell's content layer) on top of AppShell's static CSS stars. With
// prefers-reduced-motion it draws one still frame and never animates.
const STAR_COUNT = 500;
const SPEED = 2; // depth units per 60 fps frame
const MAX_RADIUS = 3;

type Star = { x: number; y: number; z: number };

export function WarpStarfield() {
	const canvasRef = useRef<HTMLCanvasElement>(null);

	useEffect(() => {
		const canvas = canvasRef.current;
		const ctx = canvas?.getContext("2d");
		if (!canvas || !ctx) return;

		let width = 0;
		let height = 0;
		const stars: Star[] = [];

		function place(star: Star) {
			star.x = (Math.random() - 0.5) * width;
			star.y = (Math.random() - 0.5) * height;
			star.z = Math.random() * width || width;
		}

		function resize() {
			if (!canvas || !ctx) return;
			const dpr = window.devicePixelRatio || 1;
			width = window.innerWidth;
			height = window.innerHeight;
			canvas.width = Math.round(width * dpr);
			canvas.height = Math.round(height * dpr);
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			stars.length = 0;
			for (let i = 0; i < STAR_COUNT; i++) {
				const star = { x: 0, y: 0, z: 0 };
				place(star);
				stars.push(star);
			}
		}

		function draw() {
			if (!ctx) return;
			ctx.clearRect(0, 0, width, height);
			for (const star of stars) {
				const sx = (star.x / star.z) * width + width / 2;
				const sy = (star.y / star.z) * height + height / 2;
				if (sx < 0 || sx > width || sy < 0 || sy > height) continue;
				const closeness = 1 - star.z / width;
				ctx.fillStyle = `rgba(255, 255, 255, ${0.25 + 0.75 * closeness})`;
				ctx.beginPath();
				ctx.arc(sx, sy, Math.max(closeness * MAX_RADIUS, 0.3), 0, Math.PI * 2);
				ctx.fill();
			}
		}

		resize();
		window.addEventListener("resize", resize);

		const reduceMotion = window.matchMedia(
			"(prefers-reduced-motion: reduce)",
		).matches;
		if (reduceMotion) {
			draw();
			return () => window.removeEventListener("resize", resize);
		}

		let frame = 0;
		let last = performance.now();
		function animate(now: number) {
			// Scale by elapsed time so the speed is the same at 60 Hz and 120 Hz.
			const step = SPEED * Math.min((now - last) / (1000 / 60), 3);
			last = now;
			for (const star of stars) {
				star.z -= step;
				if (star.z <= 0) place(star);
			}
			draw();
			frame = requestAnimationFrame(animate);
		}
		frame = requestAnimationFrame(animate);

		return () => {
			cancelAnimationFrame(frame);
			window.removeEventListener("resize", resize);
		};
	}, []);

	return (
		<div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10">
			<canvas ref={canvasRef} className="size-full" />
		</div>
	);
}

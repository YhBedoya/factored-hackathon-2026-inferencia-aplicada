import { createFileRoute } from "@tanstack/react-router";

import { CardyShowcase } from "@/components/landing/CardyShowcase";
import { FloatingCardy } from "@/components/landing/FloatingCardy";
import { Footer } from "@/components/landing/Footer";
import { Hero } from "@/components/landing/Hero";
import { Nav } from "@/components/landing/Nav";
import { WarpStarfield } from "@/components/landing/WarpStarfield";

export const Route = createFileRoute("/")({
	component: LandingPage,
});

// Sections follow the SwipLanding v2 export; the language toggle comes from
// `AppShell`, and the moving starfield sits behind the sections.
function LandingPage() {
	return (
		<>
			<WarpStarfield />
			{/* The first screen is only the controls and the hero; Cardy starts below the fold. */}
			<div className="flex min-h-svh flex-col">
				<Nav />
				<Hero />
			</div>
			<CardyShowcase />
			<Footer />
			<FloatingCardy />
		</>
	);
}

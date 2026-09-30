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
			<Nav />
			<Hero />
			<CardyShowcase />
			<Footer />
			<FloatingCardy />
		</>
	);
}

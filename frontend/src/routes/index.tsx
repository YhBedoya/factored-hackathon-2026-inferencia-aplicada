import { createFileRoute } from "@tanstack/react-router";

import { LoginDialog } from "@/components/auth/LoginDialog";
import { CardyShowcase } from "@/components/landing/CardyShowcase";
import { FloatingCardy } from "@/components/landing/FloatingCardy";
import { Footer } from "@/components/landing/Footer";
import { Hero } from "@/components/landing/Hero";
import { Nav } from "@/components/landing/Nav";
import { WarpStarfield } from "@/components/landing/WarpStarfield";

type LandingSearch = { login?: true };

// `?login=true` (or `?login=1`, what `lib/api.ts` sends) opens the login
// pop-up; anything else drops the key from the URL.
function parseSearch(search: Record<string, unknown>): LandingSearch {
	const login = search.login;
	return login === true || login === 1 || login === "1" || login === "true"
		? { login: true }
		: {};
}

export const Route = createFileRoute("/")({
	validateSearch: parseSearch,
	component: LandingPage,
});

// Sections follow the SwipLanding v2 export; the language toggle comes from
// `AppShell`, and the moving starfield sits behind the sections.
function LandingPage() {
	const search = Route.useSearch();
	const navigate = Route.useNavigate();
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
			<LoginDialog
				open={search.login === true}
				onOpenChange={(open) => {
					if (!open) {
						navigate({ search: {}, replace: true });
					}
				}}
			/>
		</>
	);
}

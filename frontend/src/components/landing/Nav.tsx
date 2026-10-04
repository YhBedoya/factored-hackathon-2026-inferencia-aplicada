import { Link } from "@tanstack/react-router";

import { LanguageToggle } from "@/components/layout/LanguageToggle";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

import { DemoAccessMenu } from "./DemoAccessMenu";
import { SoonButton } from "./SoonButton";

// No bar: the login buttons end at the content column's right edge and the
// language toggle sits at the far right of the page. The right padding only
// grows when the page is too narrow for the toggle to clear the buttons.
// AppShell hides its own header on `/`, so the toggle lives here instead.
// The judges' quick access (ADR-036) mirrors it in the top-left corner; it
// renders nothing unless the backend runs with `DEMO_QUICK_LOGIN=true`.
export function Nav() {
	const { t } = useI18n();
	return (
		<nav aria-label={t("landing.nav.label")} className="relative w-full">
			<div className="mx-auto flex max-w-6xl flex-wrap items-center justify-end gap-2 pt-4 pr-[9.5rem] pl-4 sm:pt-6 sm:pr-[max(2rem,calc(7rem-max(0px,(100vw-72rem)/2)))] sm:pl-8">
				<Button
					asChild
					variant="outline"
					className="h-10 rounded-full px-4 text-sm font-semibold"
				>
					<Link to="/" search={{ login: true }}>
						{t("landing.cta")}
					</Link>
				</Button>
				<span className="hidden sm:inline-flex">
					<SoonButton label={t("landing.nav.open")} />
				</span>
			</div>
			<div className="absolute top-4 left-4 sm:top-6 sm:left-6">
				<DemoAccessMenu />
			</div>
			<div className="absolute top-5 right-4 sm:top-7 sm:right-6">
				<LanguageToggle />
			</div>
		</nav>
	);
}

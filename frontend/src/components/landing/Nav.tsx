import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

import { SoonButton } from "./SoonButton";

export function Nav() {
	const { t } = useI18n();
	return (
		<nav
			aria-label={t("landing.nav.label")}
			className="border-b border-border bg-background/95 backdrop-blur"
		>
			<div className="mx-auto flex min-h-16 max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 sm:px-8">
				<a
					href="#inicio"
					className="flex items-center gap-2.5 rounded-md font-heading text-3xl font-bold tracking-tight text-foreground focus-visible:outline-2 focus-visible:outline-cyan sm:text-4xl"
				>
					<span
						aria-hidden="true"
						className="size-3 rounded-[3px] bg-cyan sm:size-3.5"
					/>
					Swip
				</a>
				<div className="hidden flex-1 justify-center md:flex">
					<Link
						to="/login"
						className="rounded-md text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-cyan"
					>
						{t("landing.nav.help")}
					</Link>
				</div>
				<div className="ml-auto flex items-center gap-2">
					<Button
						asChild
						variant="outline"
						className="h-10 rounded-full px-4 text-sm font-semibold"
					>
						<Link to="/login">{t("landing.cta")}</Link>
					</Button>
					<span className="hidden sm:inline-flex">
						<SoonButton label={t("landing.nav.open")} />
					</span>
				</div>
			</div>
		</nav>
	);
}

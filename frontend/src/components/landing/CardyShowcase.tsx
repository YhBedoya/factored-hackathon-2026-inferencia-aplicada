import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

const ITEMS = [
	"landing.cardy.item1",
	"landing.cardy.item2",
	"landing.cardy.item3",
] as const;

export function CardyShowcase() {
	const { t } = useI18n();
	return (
		<section
			id="cardy"
			className="border-y border-border bg-card/50"
			aria-labelledby="cardy-title"
		>
			<div className="mx-auto grid max-w-6xl items-start gap-8 px-4 py-14 sm:px-8 md:grid-cols-2 md:py-24">
				<h2
					id="cardy-title"
					className="text-3xl leading-[1.08] font-bold tracking-tight text-balance md:text-5xl"
				>
					{t("landing.cardy.title")}
				</h2>
				<div className="flex flex-col items-start gap-5">
					<p className="text-pretty text-foreground">
						{t("landing.cardy.body")}
					</p>
					<ul className="flex flex-col gap-3">
						{ITEMS.map((key) => (
							<li key={key} className="flex gap-3 text-pretty text-foreground">
								<span
									aria-hidden="true"
									className="mt-2 size-2 shrink-0 rounded-[2px] bg-cyan"
								/>
								{t(key)}
							</li>
						))}
					</ul>
					<p className="font-semibold text-pretty text-foreground">
						{t("landing.cardy.closing")}
					</p>
					<Button
						asChild
						className="h-12 rounded-full px-7 text-base font-semibold"
					>
						<Link to="/login">{t("landing.cardy.cta")}</Link>
					</Button>
				</div>
			</div>
		</section>
	);
}

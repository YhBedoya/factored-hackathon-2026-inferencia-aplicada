import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useI18n } from "@/lib/i18n";

// Always-visible entry to Cardy: a link, not a toggle, since the chat needs a
// session and lives behind /login. The bubble shows only between the hero (which
// has its own Cardy bubble) and the footer (whose team column it would cover).
export function FloatingCardy() {
	const { t } = useI18n();
	const [heroInView, setHeroInView] = useState(true);
	const [footerInView, setFooterInView] = useState(false);
	const hidden = heroInView || footerInView;

	useEffect(() => {
		const hero = document.getElementById("inicio");
		const footer = document.getElementById("pie");
		// The hero counts as "in view" while at least half of it is visible, so a
		// page shorter than hero + viewport still reaches the "scrolled past" state.
		const heroObserver = new IntersectionObserver(
			([entry]) => setHeroInView(entry.intersectionRatio >= 0.5),
			{ threshold: [0, 0.5, 1] },
		);
		const footerObserver = new IntersectionObserver(([entry]) =>
			setFooterInView(entry.isIntersecting),
		);
		if (hero) heroObserver.observe(hero);
		else setHeroInView(false);
		if (footer) footerObserver.observe(footer);
		return () => {
			heroObserver.disconnect();
			footerObserver.disconnect();
		};
	}, []);

	return (
		<div className="fixed right-3 bottom-3 z-30 flex flex-col items-end gap-2 sm:right-7 sm:bottom-7">
			<p
				aria-hidden={hidden}
				className={`hidden w-80 rounded-2xl border border-border bg-card p-4 text-sm shadow-2xl transition-opacity duration-300 motion-reduce:transition-none sm:block ${
					hidden ? "pointer-events-none opacity-0" : "opacity-100"
				}`}
			>
				{t("landing.floating.bubble")}
			</p>
			<Link
				to="/login"
				className="flex items-center gap-2.5 rounded-full border border-cyan bg-card py-2 pr-4 pl-2 text-sm font-semibold whitespace-nowrap shadow-2xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
			>
				<span
					aria-hidden="true"
					className="grid size-8 place-items-center rounded-full bg-cyan/20 font-heading text-cyan"
				>
					C
				</span>
				{t("landing.floating.label")}
			</Link>
		</div>
	);
}

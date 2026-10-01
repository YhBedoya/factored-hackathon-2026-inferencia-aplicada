import { Link } from "@tanstack/react-router";

import { useI18n } from "@/lib/i18n";

const heading =
	"text-xs font-semibold tracking-wider text-muted-foreground uppercase";

export function Footer() {
	const { t } = useI18n();
	return (
		<footer id="pie" className="border-t border-border">
			<div className="mx-auto grid max-w-6xl gap-8 px-4 pt-12 pb-24 sm:px-8 md:grid-cols-3">
				<div className="flex flex-col gap-3">
					<span className="flex items-center gap-2 font-heading text-xl font-bold">
						<span aria-hidden="true" className="size-2 rounded-[3px] bg-cyan" />
						Swip
					</span>
					<p className="text-sm text-pretty text-muted-foreground">
						{t("landing.footer.about")}
					</p>
				</div>
				<div className="flex flex-col gap-2.5 text-sm">
					<span className={heading}>Swip</span>
					<Link to="/login" className="rounded-md hover:text-cyan">
						{t("landing.nav.help")}
					</Link>
					<Link to="/login" className="rounded-md hover:text-cyan">
						{t("landing.cta")}
					</Link>
				</div>
				<div className="flex flex-col gap-2.5 text-sm">
					<span className={heading}>{t("landing.footer.team")}</span>
					<span>Yhorman Bedoya &amp; Luisa Jiménez</span>
				</div>
			</div>
		</footer>
	);
}

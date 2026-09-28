import { createFileRoute, Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/")({
	component: LandingPage,
});

function LandingPage() {
	const { t } = useI18n();

	return (
		<div className="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
			<h1 className="font-heading text-4xl text-foreground">
				{t("landing.title")}
			</h1>
			<p className="text-lg text-muted-foreground">{t("landing.subtitle")}</p>
			<Button asChild size="lg">
				<Link to="/login">{t("landing.cta")}</Link>
			</Button>
		</div>
	);
}

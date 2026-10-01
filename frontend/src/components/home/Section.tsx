import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

// One frame for every home block: title plus the three states each section
// must translate (D10). `state` picks what the body shows.
export function Section({
	title,
	testId,
	state,
	children,
	emptyText,
}: {
	title: string;
	testId: string;
	state: "loading" | "error" | "empty" | "ready";
	children?: ReactNode;
	emptyText: string;
}) {
	const { t } = useI18n();
	return (
		<section data-testid={testId} className="flex flex-col gap-3">
			<h2 className="font-heading text-lg text-foreground">{title}</h2>
			{state === "loading" && (
				<Card role="status" aria-label={t("home.loading")}>
					<div className="mx-4 h-16 animate-pulse rounded-lg bg-muted" />
				</Card>
			)}
			{state === "error" && (
				<p role="alert" className="text-sm text-alert">
					{t("home.error")}
				</p>
			)}
			{state === "empty" && (
				<p className="text-sm text-muted-foreground">{emptyText}</p>
			)}
			{state === "ready" && children}
		</section>
	);
}

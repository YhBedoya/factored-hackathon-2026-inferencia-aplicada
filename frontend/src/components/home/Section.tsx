import type { ReactNode } from "react";

import { useI18n } from "@/lib/i18n";

export type SectionState = "loading" | "error" | "empty" | "ready";

// One panel frame for the home blocks ("Swip Panel" design): title, an
// optional header action, plus the three states each block must translate
// (D10). `state` picks what the body shows.
export function Section({
	title,
	testId,
	state,
	children,
	emptyText,
	action,
	className = "",
}: {
	title: string;
	testId: string;
	state: SectionState;
	children?: ReactNode;
	emptyText: string;
	action?: ReactNode;
	className?: string;
}) {
	return (
		<section
			data-testid={testId}
			className={`relative flex flex-col gap-6 overflow-hidden rounded-[20px] border border-border bg-card p-7 ${className}`}
		>
			<div className="flex items-center justify-between gap-4">
				<h2 className="font-heading text-[22px] font-bold text-foreground">
					{title}
				</h2>
				{action}
			</div>
			<SectionBody state={state} emptyText={emptyText}>
				{children}
			</SectionBody>
		</section>
	);
}

export function SectionBody({
	state,
	emptyText,
	children,
}: {
	state: SectionState;
	emptyText: string;
	children?: ReactNode;
}) {
	const { t } = useI18n();
	return (
		<>
			{state === "loading" && (
				<div
					role="status"
					aria-label={t("home.loading")}
					className="h-16 animate-pulse rounded-xl bg-muted"
				/>
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
		</>
	);
}

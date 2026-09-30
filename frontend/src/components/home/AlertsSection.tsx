import { Button } from "@/components/ui/button";
import { type TKey, useI18n } from "@/lib/i18n";

import { useCardDetails, useCards, useFirstPage } from "./queries";

const DECLINE_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

type Alert = { key: string; text: string; prompt: string };

// D10 / plan gate: alerts are computed here from the `/me` responses. The
// decline window uses the browser clock (now - 7 days), no server flag.
export function AlertsSection({ onAsk }: { onAsk: (prompt: string) => void }) {
	const { t } = useI18n();
	const cards = useCards();
	const credit = (cards.data ?? []).filter((c) => c.kind === "credit");
	const details = useCardDetails(credit.map((c) => c.card_id));
	const firstPage = useFirstPage();

	const alerts: Alert[] = [];
	for (const card of cards.data ?? []) {
		if (card.status === "Blocked" || card.status === "Suspended") {
			alerts.push({
				key: `status-${card.card_id}`,
				text: t(`home.alerts.status.${card.status}` as TKey, {
					mask: card.mask,
				}),
				prompt: t(`home.ask.status.${card.status}` as TKey, {
					mask: card.mask,
				}),
			});
		}
	}
	for (const q of details) {
		if (q.data && (q.data.days_past_due ?? 0) > 0) {
			alerts.push({
				key: `due-${q.data.card_id}`,
				text: t("home.alerts.past_due", { mask: q.data.mask }),
				prompt: t("home.ask.past_due", { mask: q.data.mask }),
			});
		}
	}
	const cutoff = Date.now() - DECLINE_WINDOW_MS;
	const declined = firstPage.data?.items.find((x) => x.status === "Declined");
	if (declined && new Date(declined.occurred_at).getTime() >= cutoff) {
		alerts.push({
			key: `declined-${declined.tx_id}`,
			text: t("home.alerts.declined", {
				merchant: declined.merchant_name ?? t("home.tx.no_merchant"),
				date: declined.date_display,
			}),
			prompt: t("home.ask.declined"),
		});
	}

	const loading = cards.isPending || firstPage.isPending;
	const failed = cards.isError || firstPage.isError;
	const quick: { key: string; label: TKey; prompt: TKey }[] = [
		{ key: "lock", label: "home.quick.lock", prompt: "home.ask.lock" },
		{
			key: "replace",
			label: "home.quick.replace",
			prompt: "home.ask.replace",
		},
		{ key: "dispute", label: "home.quick.dispute", prompt: "home.ask.dispute" },
		{ key: "why", label: "home.quick.why", prompt: "home.ask.why" },
	];

	return (
		<>
			<section className="flex flex-col gap-3">
				<h2 className="font-heading text-lg text-foreground">
					{t("home.alerts.title")}
				</h2>
				{loading && (
					<div
						role="status"
						aria-label={t("home.loading")}
						className="h-12 animate-pulse rounded-lg bg-muted"
					/>
				)}
				{!loading && failed && (
					<p role="alert" className="text-sm text-alert">
						{t("home.error")}
					</p>
				)}
				{!loading && !failed && alerts.length === 0 && (
					<p className="text-sm text-muted-foreground">
						{t("home.alerts.empty")}
					</p>
				)}
				{alerts.map((a) => (
					<div
						key={a.key}
						data-testid="home-alert"
						className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3 text-sm ring-1 ring-gold/40"
					>
						<span className="text-foreground">{a.text}</span>
						<Button
							type="button"
							size="sm"
							variant="outline"
							onClick={() => onAsk(a.prompt)}
						>
							{t("home.alerts.ask")}
						</Button>
					</div>
				))}
			</section>
			<section className="flex flex-col gap-3">
				<h2 className="font-heading text-lg text-foreground">
					{t("home.quick.title")}
				</h2>
				<div className="flex flex-wrap gap-2">
					{quick.map((q) => (
						<Button
							key={q.key}
							type="button"
							variant="outline"
							data-testid="home-quick-action"
							onClick={() => onAsk(t(q.prompt))}
						>
							{t(q.label)}
						</Button>
					))}
				</div>
			</section>
		</>
	);
}

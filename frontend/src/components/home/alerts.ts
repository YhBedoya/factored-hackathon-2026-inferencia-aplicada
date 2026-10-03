import { type TKey, useI18n } from "@/lib/i18n";

import { useCardDetails, useCards, useFirstPage } from "./queries";

const DECLINE_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

export type HomeAlert = { key: string; text: string; prompt: string };

// The four Cardy shortcuts (sidebar chips). Each only prefills the composer.
export const QUICK_ACTIONS: { key: string; label: TKey; prompt: TKey }[] = [
	{ key: "lock", label: "home.quick.lock", prompt: "home.ask.lock" },
	{ key: "replace", label: "home.quick.replace", prompt: "home.ask.replace" },
	{ key: "dispute", label: "home.quick.dispute", prompt: "home.ask.dispute" },
	{ key: "why", label: "home.quick.why", prompt: "home.ask.why" },
];

// D10 / plan gate: alerts are computed here from the `/me` responses (the
// bell in `HomeNav`). The decline window uses the browser clock
// (now - 7 days), no server flag.
export function useHomeAlerts(): {
	alerts: HomeAlert[];
	loading: boolean;
	failed: boolean;
} {
	const { t } = useI18n();
	const cards = useCards();
	const credit = (cards.data ?? []).filter((c) => c.kind === "credit");
	const details = useCardDetails(credit.map((c) => c.card_id));
	const firstPage = useFirstPage();

	const alerts: HomeAlert[] = [];
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

	return {
		alerts,
		loading: cards.isPending || firstPage.isPending,
		failed: cards.isError || firstPage.isError,
	};
}

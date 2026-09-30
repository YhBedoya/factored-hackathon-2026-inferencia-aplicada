import { Card } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

import { useCardDetails, useCards } from "./queries";
import { Section } from "./Section";

// A1: only credit cards have a balance; debit never shows one. The bar is the
// ratio of the raw numbers; every shown amount and date is the server's string.
export function BalanceSection() {
	const { t } = useI18n();
	const cards = useCards();
	const credit = (cards.data ?? []).filter((c) => c.kind === "credit");
	const details = useCardDetails(credit.map((c) => c.card_id));
	const pending = cards.isPending || details.some((d) => d.isPending);
	const failed = cards.isError || details.some((d) => d.isError);
	const state = pending
		? "loading"
		: failed
			? "error"
			: credit.length === 0
				? "empty"
				: "ready";
	return (
		<Section
			title={t("home.balance.title")}
			testId="home-balance"
			state={state}
			emptyText={t("home.balance.empty")}
		>
			<div className="grid gap-3 sm:grid-cols-2">
				{details.map((q) => {
					const d = q.data;
					if (!d) {
						return null;
					}
					const limit = Number(d.credit_limit);
					const used = limit > 0 ? Number(d.current_balance) / limit : 0;
					const pct = Math.min(100, Math.max(0, Math.round(used * 100)));
					return (
						<Card key={d.card_id}>
							<div className="flex flex-col gap-2 px-4">
								<span className="font-heading text-foreground">{d.mask}</span>
								<dl className="grid grid-cols-2 gap-1 text-sm">
									<dt className="text-muted-foreground">
										{t("home.balance.limit")}
									</dt>
									<dd>{d.credit_limit_display}</dd>
									<dt className="text-muted-foreground">
										{t("home.balance.current")}
									</dt>
									<dd>{d.current_balance_display}</dd>
									<dt className="text-muted-foreground">
										{t("home.balance.available")}
									</dt>
									<dd>{d.available_credit_display}</dd>
									<dt className="text-muted-foreground">
										{t("home.balance.expires")}
									</dt>
									<dd>{d.expiration_date_display}</dd>
								</dl>
								<div
									className="h-2 overflow-hidden rounded-full bg-muted"
									role="progressbar"
									aria-label={t("home.balance.usage")}
									aria-valuemin={0}
									aria-valuemax={100}
									aria-valuenow={pct}
								>
									<div
										className="h-full bg-cyan"
										style={{ width: `${pct}%` }}
									/>
								</div>
							</div>
						</Card>
					);
				})}
			</div>
		</Section>
	);
}

import { Card } from "@/components/ui/card";
import { type TKey, useI18n } from "@/lib/i18n";

import { useCards } from "./queries";
import { Section } from "./Section";

export function CardsSection() {
	const { t } = useI18n();
	const { data, isPending, isError } = useCards();
	const state = isPending
		? "loading"
		: isError
			? "error"
			: data.length === 0
				? "empty"
				: "ready";
	return (
		<Section
			title={t("home.cards.title")}
			testId="home-cards"
			state={state}
			emptyText={t("home.cards.empty")}
		>
			<div className="grid gap-3 sm:grid-cols-2">
				{data?.map((card) => (
					<Card key={card.card_id} data-testid="home-card">
						<div className="flex flex-col gap-1 px-4">
							<span className="text-sm text-muted-foreground">
								{t(`home.cards.kind.${card.kind}` as TKey)}
							</span>
							<span className="font-heading text-lg text-foreground">
								{card.mask}
							</span>
							<span className="text-sm text-cyan">
								{t(
									(card.locked
										? "home.cards.locked"
										: `home.cards.status.${card.status}`) as TKey,
								)}
							</span>
						</div>
					</Card>
				))}
			</div>
		</Section>
	);
}

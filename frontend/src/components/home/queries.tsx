import { useQueries, useQuery } from "@tanstack/react-query";

import type { CardDetailsView, CardView } from "@/client";
import { getMyCard, listMyCards, listMyTransactions } from "@/lib/api";

import type { SectionState } from "./Section";

// Shared by the sections and the alerts so one fetch serves all of them.
export const CARDS_KEY = ["home", "cards"] as const;
export const cardKey = (cardId: string) => ["home", "card", cardId] as const;
export const FIRST_PAGE_KEY = ["home", "tx-first"] as const;

export function useCards() {
	return useQuery({ queryKey: CARDS_KEY, queryFn: listMyCards, retry: false });
}

export function useCardDetails(cardIds: string[]) {
	return useQueries({
		queries: cardIds.map((id) => ({
			queryKey: cardKey(id),
			queryFn: () => getMyCard(id),
			retry: false,
		})),
	});
}

export function useFirstPage() {
	return useQuery({
		queryKey: FIRST_PAGE_KEY,
		queryFn: () => listMyTransactions(),
		retry: false,
	});
}

/** Every card plus its details, keyed by `card_id`, and one state for the lot. */
export function useHomeCards(): {
	cards: CardView[];
	details: Record<string, CardDetailsView | undefined>;
	state: SectionState;
} {
	const cards = useCards();
	const list = cards.data ?? [];
	const queries = useCardDetails(list.map((c) => c.card_id));
	const details: Record<string, CardDetailsView | undefined> = {};
	for (const q of queries) {
		if (q.data) {
			details[q.data.card_id] = q.data;
		}
	}
	const state: SectionState =
		cards.isPending || queries.some((q) => q.isPending)
			? "loading"
			: cards.isError || queries.some((q) => q.isError)
				? "error"
				: list.length === 0
					? "empty"
					: "ready";
	return { cards: list, details, state };
}

/**
 * The amount a card shows (A1, ADR-034): a debit card's balance is the money
 * available in it; a credit card shows its available credit. Always the
 * server's display string (R4).
 */
export function cardAmount(
	details: CardDetailsView | undefined,
): string | null {
	if (!details) {
		return null;
	}
	return details.kind === "debit"
		? details.current_balance_display
		: details.available_credit_display;
}

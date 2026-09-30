import { useQueries, useQuery } from "@tanstack/react-query";

import { getMyCard, listMyCards, listMyTransactions } from "@/lib/api";

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

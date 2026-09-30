import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { listMyTransactions } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

import { useCards } from "./queries";

export function TransactionsSection() {
	const { t } = useI18n();
	const cards = useCards();
	const [cardId, setCardId] = useState("");
	const [dateFrom, setDateFrom] = useState("");
	const [dateTo, setDateTo] = useState("");
	const query = useInfiniteQuery({
		queryKey: ["home", "tx", cardId, dateFrom, dateTo],
		queryFn: ({ pageParam }) =>
			listMyTransactions({
				cardId,
				dateFrom,
				dateTo,
				cursor: pageParam ?? undefined,
			}),
		initialPageParam: null as string | null,
		getNextPageParam: (last) => last.next_cursor,
		retry: false,
	});
	const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
	const state = query.isPending
		? "loading"
		: query.isError
			? "error"
			: rows.length === 0
				? "empty"
				: "ready";
	const fieldClass =
		"h-8 rounded-lg border border-input bg-transparent px-2 text-sm text-foreground";

	return (
		<section data-testid="home-transactions" className="flex flex-col gap-3">
			<h2 className="font-heading text-lg text-foreground">
				{t("home.tx.title")}
			</h2>
			<div className="flex flex-wrap items-end gap-3">
				<label className="flex flex-col gap-1 text-sm text-muted-foreground">
					{t("home.tx.filter_card")}
					<select
						className={fieldClass}
						value={cardId}
						onChange={(e) => setCardId(e.target.value)}
					>
						<option value="">{t("home.tx.all_cards")}</option>
						{cards.data?.map((c) => (
							<option key={c.card_id} value={c.card_id}>
								{c.mask}
							</option>
						))}
					</select>
				</label>
				<label
					htmlFor="tx-from"
					className="flex flex-col gap-1 text-sm text-muted-foreground"
				>
					{t("home.tx.date_from")}
					<Input
						id="tx-from"
						type="date"
						value={dateFrom}
						onChange={(e) => setDateFrom(e.target.value)}
					/>
				</label>
				<label
					htmlFor="tx-to"
					className="flex flex-col gap-1 text-sm text-muted-foreground"
				>
					{t("home.tx.date_to")}
					<Input
						id="tx-to"
						type="date"
						value={dateTo}
						onChange={(e) => setDateTo(e.target.value)}
					/>
				</label>
			</div>
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
				<p className="text-sm text-muted-foreground">{t("home.tx.empty")}</p>
			)}
			{state === "ready" && (
				<ul className="flex flex-col divide-y divide-border rounded-xl ring-1 ring-foreground/10">
					{rows.map((tx) => (
						<li
							key={tx.tx_id}
							data-testid="home-tx-row"
							className="flex items-center justify-between gap-3 px-4 py-3 text-sm"
						>
							<div className="flex min-w-0 flex-col">
								<span className="truncate text-foreground">
									{tx.merchant_name ?? t("home.tx.no_merchant")}
								</span>
								<span className="text-muted-foreground">{tx.date_display}</span>
							</div>
							<div className="flex flex-col items-end">
								<span className="text-foreground">{tx.amount_display}</span>
								<span
									className={
										tx.status === "Declined" ? "text-alert" : "text-gold"
									}
								>
									{t(`home.tx.status.${tx.status}` as TKey)}
								</span>
							</div>
						</li>
					))}
				</ul>
			)}
			{state === "ready" && query.hasNextPage && (
				<Button
					type="button"
					variant="outline"
					data-testid="home-tx-more"
					disabled={query.isFetchingNextPage}
					onClick={() => query.fetchNextPage()}
				>
					{t("home.tx.more")}
				</Button>
			)}
		</section>
	);
}

import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronDownIcon } from "lucide-react";
import { type ReactNode, useState } from "react";

import type { CardView, TxRow } from "@/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { listMyTransactions } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

import { HIDDEN_AMOUNT } from "./MyCardsSection";
import { SectionBody, type SectionState } from "./Section";

type Filter = "all" | "in" | "out";

// Plan decision: "Ingresos" and "Gastos" are picked by transaction type;
// `Transfer`/`Adjustment` only show under "Todos".
const INCOME = new Set(["Deposit", "Payment"]);
const EXPENSE = new Set(["Purchase", "Withdrawal"]);
const TYPES = new Set([...INCOME, ...EXPENSE, "Transfer", "Adjustment"]);
const FILTERS: Filter[] = ["all", "in", "out"];

const STATUS_COLOR: Record<TxRow["status"], string> = {
	Approved: "text-ok",
	Pending: "text-gold",
	Declined: "text-alert",
	Reversed: "text-muted-foreground",
};

function matches(tx: TxRow, filter: Filter): boolean {
	if (filter === "in") {
		return INCOME.has(tx.type);
	}
	if (filter === "out") {
		return EXPENSE.has(tx.type);
	}
	return true;
}

// "Movimientos recientes" for the selected card. The type chips filter the
// pages already loaded, in the browser; the date range and "Ver más" go to
// the server (`/me/transactions`, cursor paging). Display strings are the
// server's (R4).
export function TransactionsSection({
	card,
	cardName,
	hideBalances,
	onAsk,
}: {
	card: CardView | undefined;
	cardName: string;
	hideBalances: boolean;
	onAsk: (prompt: string) => void;
}) {
	const { t } = useI18n();
	const cardId = card?.card_id ?? "";
	const [filter, setFilter] = useState<Filter>("all");
	const [openId, setOpenId] = useState<string | null>(null);
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
		enabled: cardId !== "",
		retry: false,
	});
	const rows = (query.data?.pages.flatMap((p) => p.items) ?? []).filter((tx) =>
		matches(tx, filter),
	);
	const state: SectionState =
		cardId === "" || query.isPending
			? "loading"
			: query.isError
				? "error"
				: rows.length === 0
					? "empty"
					: "ready";
	const fieldClass = "h-8 w-40 rounded-full border-border bg-card/50 px-3";

	return (
		<section
			data-testid="home-transactions"
			className="flex flex-col rounded-[20px] border border-border bg-card pt-7 pb-2"
		>
			<div className="flex items-center justify-between gap-4 px-7 pb-4">
				<div className="flex flex-col gap-0.5">
					<h2 className="font-heading text-[22px] font-bold">
						{t("home.tx.title")}
					</h2>
					{card && (
						<span className="text-[13px] text-muted-foreground">
							{cardName} {card.mask}
						</span>
					)}
				</div>
				<fieldset
					aria-label={t("home.tx.filter.label")}
					className="flex gap-1.5 rounded-full border border-border p-1"
				>
					{FILTERS.map((key) => (
						<button
							key={key}
							type="button"
							data-testid={`home-tx-filter-${key}`}
							aria-pressed={filter === key}
							onClick={() => {
								setFilter(key);
								setOpenId(null);
							}}
							className={`cursor-pointer rounded-full px-3.5 py-1.5 text-[13px] font-semibold ${filter === key ? "bg-cyan text-bg" : "text-muted-foreground hover:text-foreground"}`}
						>
							{t(`home.tx.filter.${key}` as TKey)}
						</button>
					))}
				</fieldset>
			</div>
			<div className="flex items-end gap-3 px-7 pb-4">
				<label
					htmlFor="tx-from"
					className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground"
				>
					{t("home.tx.date_from")}
					<Input
						id="tx-from"
						type="date"
						className={fieldClass}
						value={dateFrom}
						onChange={(e) => setDateFrom(e.target.value)}
					/>
				</label>
				<label
					htmlFor="tx-to"
					className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground"
				>
					{t("home.tx.date_to")}
					<Input
						id="tx-to"
						type="date"
						className={fieldClass}
						value={dateTo}
						onChange={(e) => setDateTo(e.target.value)}
					/>
				</label>
			</div>
			{state !== "ready" && (
				<div className="border-t border-border px-7 py-7 text-center">
					<SectionBody state={state} emptyText={t("home.tx.empty")} />
				</div>
			)}
			{state === "ready" && (
				<ul>
					{rows.map((tx) => (
						<TxItem
							key={tx.tx_id}
							tx={tx}
							open={openId === tx.tx_id}
							onToggle={() => setOpenId(openId === tx.tx_id ? null : tx.tx_id)}
							hideBalances={hideBalances}
							onAsk={onAsk}
						/>
					))}
				</ul>
			)}
			{state !== "loading" && query.hasNextPage && (
				<div className="flex justify-center border-t border-border px-7 pt-3 pb-1">
					<Button
						type="button"
						variant="ghost"
						data-testid="home-tx-more"
						className="text-cyan"
						disabled={query.isFetchingNextPage}
						onClick={() => query.fetchNextPage()}
					>
						{t("home.tx.more")}
					</Button>
				</div>
			)}
		</section>
	);
}

function TxItem({
	tx,
	open,
	onToggle,
	hideBalances,
	onAsk,
}: {
	tx: TxRow;
	open: boolean;
	onToggle: () => void;
	hideBalances: boolean;
	onAsk: (prompt: string) => void;
}) {
	const { t } = useI18n();
	const income = INCOME.has(tx.type);
	const merchant = tx.merchant_name ?? t("home.tx.no_merchant");
	const typeLabel = TYPES.has(tx.type)
		? t(`home.tx.type.${tx.type}` as TKey)
		: tx.type;
	const detailsId = `tx-details-${tx.tx_id}`;
	return (
		<li data-testid="home-tx-row" className="border-t border-border">
			<button
				type="button"
				aria-expanded={open}
				aria-controls={detailsId}
				onClick={onToggle}
				className={`grid w-full cursor-pointer grid-cols-[44px_minmax(0,1fr)_auto_20px] items-center gap-4 px-7 py-3.5 text-left hover:bg-muted ${open ? "bg-muted" : ""}`}
			>
				<span
					aria-hidden="true"
					className={`grid size-11 place-items-center rounded-xl text-lg font-semibold ${income ? "bg-cyan/20 text-ok" : "bg-card/50 text-muted-foreground"}`}
				>
					{income ? "↓" : merchant.charAt(0).toUpperCase()}
				</span>
				<span className="flex min-w-0 flex-col gap-0.5">
					<span className="truncate font-semibold">{merchant}</span>
					<span className="text-[13px] text-muted-foreground">
						{tx.date_display} · {typeLabel}
					</span>
				</span>
				<span
					className={`font-semibold tabular-nums ${income ? "text-ok" : "text-foreground"}`}
				>
					{hideBalances ? HIDDEN_AMOUNT : tx.amount_display}
				</span>
				<ChevronDownIcon
					aria-hidden="true"
					className={`size-4 text-muted-foreground transition-transform duration-200 ${open ? "rotate-180" : ""}`}
				/>
			</button>
			{open && (
				<div
					id={detailsId}
					data-testid="home-tx-details"
					className="mr-7 mb-4 ml-[88px] grid grid-cols-3 gap-4 rounded-xl border border-border bg-card/50 px-[18px] py-4 text-sm"
				>
					<Detail label={t("home.tx.detail.date")}>{tx.date_display}</Detail>
					<Detail label={t("home.tx.detail.ref")}>
						<span className="tabular-nums">{tx.tx_id}</span>
					</Detail>
					<Detail label={t("home.tx.detail.status")}>
						<span className={`font-semibold ${STATUS_COLOR[tx.status]}`}>
							{t(`home.tx.status.${tx.status}` as TKey)}
						</span>
					</Detail>
					<div className="col-span-full flex justify-end">
						<button
							type="button"
							data-testid="home-tx-ask"
							onClick={() =>
								onAsk(t("home.ask.tx", { merchant, date: tx.date_display }))
							}
							className="cursor-pointer rounded-full border border-cyan px-3.5 py-1.5 text-[13px] font-semibold text-cyan hover:bg-cyan/10"
						>
							{t("home.tx.detail.ask")}
						</button>
					</div>
				</div>
			)}
		</li>
	);
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
	return (
		<div className="flex min-w-0 flex-col gap-0.5">
			<span className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
				{label}
			</span>
			<span className="break-all">{children}</span>
		</div>
	);
}

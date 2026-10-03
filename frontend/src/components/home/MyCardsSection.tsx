import { EyeIcon, EyeOffIcon } from "lucide-react";

import type { CardDetailsView, CardView } from "@/client";
import { type TKey, useI18n } from "@/lib/i18n";

import { cardAmount, type useHomeCards } from "./queries";
import { Section } from "./Section";

/** What a hidden amount shows instead ("Ocultar saldos"). */
export const HIDDEN_AMOUNT = "•••••••";

export function statusKey(card: CardView): TKey {
	return (
		card.locked ? "home.cards.locked" : `home.cards.status.${card.status}`
	) as TKey;
}

// "Mis tarjetas": every card, one selected at a time, then the selected
// card's amount, credit usage bar and detail rows. Every amount and date is
// the server's display string (R4); the bar is only the ratio of the raw
// numbers. "Ocultar saldos" masks every amount on the page.
export function MyCardsSection({
	home,
	selectedId,
	onSelect,
	hideBalances,
	onToggleHide,
}: {
	home: ReturnType<typeof useHomeCards>;
	selectedId: string | undefined;
	onSelect: (cardId: string) => void;
	hideBalances: boolean;
	onToggleHide: () => void;
}) {
	const { t } = useI18n();
	const selected = home.cards.find((c) => c.card_id === selectedId);
	const selectedDetails = selectedId ? home.details[selectedId] : undefined;
	const show = (text: string | null | undefined) =>
		hideBalances ? HIDDEN_AMOUNT : (text ?? "—");

	return (
		<Section
			title={t("home.cards.mine")}
			testId="home-cards"
			state={home.state}
			emptyText={t("home.cards.empty")}
			action={
				<button
					type="button"
					data-testid="home-toggle-balances"
					aria-pressed={hideBalances}
					onClick={onToggleHide}
					className="flex cursor-pointer items-center gap-2 rounded-full border border-border bg-card/50 px-4 py-2 text-sm font-semibold whitespace-nowrap hover:border-muted-foreground"
				>
					{hideBalances ? (
						<EyeIcon className="size-4" aria-hidden="true" />
					) : (
						<EyeOffIcon className="size-4" aria-hidden="true" />
					)}
					{t(hideBalances ? "home.cards.show" : "home.cards.hide")}
				</button>
			}
		>
			<div className="flex flex-col gap-2.5">
				{home.cards.map((card) => {
					const on = card.card_id === selectedId;
					const details = home.details[card.card_id];
					return (
						<button
							key={card.card_id}
							type="button"
							data-testid="home-card"
							aria-pressed={on}
							onClick={() => onSelect(card.card_id)}
							className={`grid cursor-pointer grid-cols-[150px_minmax(0,1fr)_auto_20px] items-center gap-5 rounded-2xl border py-3 pr-4 pl-3 text-left transition-colors duration-200 hover:bg-muted ${on ? "border-cyan bg-muted" : "border-border bg-card/50"}`}
						>
							<CardFace card={card} />
							<span className="flex min-w-0 flex-col gap-0.5">
								<span className="text-[17px] font-semibold">
									{t(`home.cards.name.${card.kind}` as TKey)}
								</span>
								<span className="text-[13px] text-muted-foreground">
									{card.mask}
									{details?.expiration_date_display &&
										` · ${t("home.cards.expires", { date: details.expiration_date_display })}`}
								</span>
							</span>
							<span className="flex flex-col items-end gap-0.5">
								<span className="text-xs font-semibold text-muted-foreground">
									{t(`home.balance.label.${card.kind}` as TKey)}
								</span>
								<span className="text-lg font-semibold tabular-nums">
									{show(cardAmount(details))}
								</span>
							</span>
							<span
								aria-hidden="true"
								className={`grid size-5 place-items-center rounded-full border-2 ${on ? "border-cyan" : "border-border"}`}
							>
								<span
									className={`size-2.5 rounded-full ${on ? "bg-cyan" : ""}`}
								/>
							</span>
						</button>
					);
				})}
			</div>
			{selected && selectedDetails && (
				<SelectedCard
					card={selected}
					details={selectedDetails}
					show={show}
					hideBalances={hideBalances}
				/>
			)}
		</Section>
	);
}

function CardFace({ card }: { card: CardView }) {
	const { t } = useI18n();
	const debit = card.kind === "debit";
	return (
		<span
			aria-hidden="true"
			className={`flex aspect-[1.586/1] flex-col justify-between rounded-[10px] border px-3 py-2.5 shadow-[0_8px_18px_rgba(0,0,0,.35)] ${debit ? "border-cyan bg-cyan text-bg" : "border-cyan/40 bg-muted bg-gradient-to-br from-cyan/35 via-cyan/15 to-transparent text-foreground"}`}
		>
			<span className="flex items-center justify-between">
				<span className="font-heading text-[13px] font-bold">Swip</span>
				<span
					className={`text-[9px] font-semibold tracking-[.08em] uppercase ${debit ? "text-bg" : "text-muted-foreground"}`}
				>
					{t(`home.cards.kind.${card.kind}` as TKey)}
				</span>
			</span>
			<span className="h-[15px] w-5 rounded-[3px] bg-gradient-to-br from-gold via-gold/85 to-gold/60 shadow-[inset_0_1px_0_rgb(255_255_255/0.45),0_1px_2px_rgb(0_0_0/0.35)]" />
			<span className="text-[11px] font-semibold tracking-widest">
				{card.mask}
			</span>
		</span>
	);
}

function SelectedCard({
	card,
	details,
	show,
	hideBalances,
}: {
	card: CardView;
	details: CardDetailsView;
	show: (text: string | null | undefined) => string;
	hideBalances: boolean;
}) {
	const { t } = useI18n();
	const credit = card.kind === "credit";
	const rows: { key: string; label: string; value: string }[] = [];
	if (credit) {
		rows.push(
			{
				key: "limit",
				label: t("home.balance.row.limit"),
				value: show(details.credit_limit_display),
			},
			{
				key: "current",
				label: t("home.balance.row.current"),
				value: show(details.current_balance_display),
			},
		);
	}
	rows.push({
		key: "status",
		label: t("home.balance.row.status"),
		value: t(statusKey(card)),
	});
	if (credit && (details.days_past_due ?? 0) > 0) {
		rows.push({
			key: "past_due",
			label: t("home.balance.row.past_due"),
			value: t("home.balance.days", { days: String(details.days_past_due) }),
		});
	}
	if (!credit && details.expiration_date_display) {
		rows.push({
			key: "expires",
			label: t("home.balance.row.expires"),
			value: details.expiration_date_display,
		});
	}

	const limit = Number(details.credit_limit);
	const used = limit > 0 ? Number(details.current_balance) / limit : 0;
	const pct = Math.min(100, Math.max(0, Math.round(used * 100)));
	const name = t(`home.cards.name.${card.kind}` as TKey);

	return (
		<div
			data-testid="home-balance"
			className="grid grid-cols-2 items-end gap-8 border-t border-border pt-6"
		>
			<div className="flex flex-col gap-1.5">
				<span className="text-sm font-semibold text-muted-foreground">
					{t(`home.balance.label.${card.kind}` as TKey)} · {name}
				</span>
				<span
					data-testid="home-balance-amount"
					className="text-[40px] leading-tight font-semibold tracking-tight whitespace-nowrap tabular-nums"
				>
					{show(cardAmount(details))}
				</span>
			</div>
			<div className="flex flex-col gap-2.5">
				{credit && (
					<div className="flex flex-col gap-1.5">
						<div
							className="h-2 overflow-hidden rounded-full bg-bg"
							role="progressbar"
							aria-label={t("home.balance.usage")}
							aria-valuemin={0}
							aria-valuemax={100}
							aria-valuenow={pct}
						>
							<div
								className="h-full rounded-full bg-gold"
								style={{ width: `${pct}%` }}
							/>
						</div>
						<span className="text-[13px] text-muted-foreground">
							{hideBalances
								? t("home.balance.used_hidden")
								: t("home.balance.used", {
										used: details.current_balance_display ?? "—",
										limit: details.credit_limit_display ?? "—",
									})}
						</span>
					</div>
				)}
				{rows.map((row) => (
					<div
						key={row.key}
						className="flex justify-between gap-3 border-t border-border pt-2 text-sm"
					>
						<span className="text-muted-foreground">{row.label}</span>
						<span className="font-semibold tabular-nums">{row.value}</span>
					</div>
				))}
			</div>
		</div>
	);
}

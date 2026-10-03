import { ArrowUpRightIcon, type LucideIcon, TargetIcon } from "lucide-react";

import type { CardDetailsView, CardView } from "@/client";
import { type TKey, useI18n } from "@/lib/i18n";

import { QUICK_ACTIONS } from "./alerts";

// The home's right column ("Swip Panel" design): Cardy's card with the four
// shortcuts, the two features that don't exist yet, and the selected card's
// data (mask only: the full number never reaches the frontend).
export function HomeSidebar({
	name,
	card,
	details,
	onAsk,
	onOpenCardy,
}: {
	name: string | undefined;
	card: CardView | undefined;
	details: CardDetailsView | undefined;
	onAsk: (prompt: string) => void;
	onOpenCardy: () => void;
}) {
	const { t } = useI18n();
	return (
		<div className="flex flex-col gap-6">
			<section
				data-testid="home-cardy-card"
				className="flex flex-col gap-4 rounded-[20px] border border-cyan bg-[color-mix(in_oklab,var(--color-cyan)_18%,var(--color-bg))] p-6"
			>
				<div className="flex items-center gap-3">
					<span
						aria-hidden="true"
						className="grid size-11 place-items-center rounded-full border border-cyan bg-bg font-heading text-[19px] text-cyan"
					>
						C
					</span>
					<div className="flex flex-col">
						<span className="font-heading text-[19px] font-bold">Cardy</span>
						<span className="flex items-center gap-1.5 text-[13px]">
							<span
								aria-hidden="true"
								className="size-[7px] rounded-full bg-ok"
							/>
							{t("home.cardy.subtitle")}
						</span>
					</div>
				</div>
				{name && (
					<p className="text-[15px] text-pretty">
						{t("home.cardy.hello", { name })}
					</p>
				)}
				<div className="flex flex-wrap gap-2">
					{QUICK_ACTIONS.map((q) => (
						<button
							key={q.key}
							type="button"
							data-testid="home-quick-action"
							onClick={() => onAsk(t(q.prompt))}
							className="cursor-pointer rounded-full border border-cyan bg-bg px-3.5 py-1.5 text-[13px] font-semibold hover:bg-cyan/10"
						>
							{t(q.label)}
						</button>
					))}
				</div>
				<button
					type="button"
					data-testid="home-cardy-talk"
					onClick={onOpenCardy}
					className="cursor-pointer self-start rounded-full bg-cyan px-[22px] py-[11px] text-[15px] font-semibold text-bg transition-transform duration-200 hover:translate-x-[3px]"
				>
					{t("home.cardy.talk")}
				</button>
			</section>

			<section className="flex flex-col gap-3">
				<SoonTile
					icon={ArrowUpRightIcon}
					title="home.soon.transfer"
					body="home.soon.transfer_body"
				/>
				<SoonTile
					icon={TargetIcon}
					title="home.soon.savings"
					body="home.soon.savings_body"
				/>
			</section>

			{card && (
				<section
					data-testid="home-card-data"
					className="flex flex-col gap-3.5 rounded-[20px] border border-border bg-card p-6"
				>
					<h2 className="font-heading text-[22px] font-bold">
						{t("home.data.title")}
					</h2>
					{name && <DataRow label={t("home.data.holder")} value={name} />}
					<DataRow
						label={t("home.data.card")}
						value={t(`home.cards.name.${card.kind}` as TKey)}
					/>
					<DataRow label={t("home.data.number")} value={card.mask} />
					{details?.expiration_date_display && (
						<DataRow
							label={t("home.data.expires")}
							value={details.expiration_date_display}
						/>
					)}
				</section>
			)}
		</div>
	);
}

function SoonTile({
	icon: Icon,
	title,
	body,
}: {
	icon: LucideIcon;
	title: TKey;
	body: TKey;
}) {
	const { t } = useI18n();
	return (
		<div
			aria-disabled="true"
			className="flex cursor-not-allowed items-center gap-3.5 rounded-2xl border border-dashed border-border bg-card/50 px-[18px] py-4"
		>
			<span
				aria-hidden="true"
				className="grid size-[42px] flex-none place-items-center rounded-xl bg-cyan/20 text-muted-foreground"
			>
				<Icon className="size-5" />
			</span>
			<div className="flex min-w-0 flex-1 flex-col gap-0.5">
				<span className="font-semibold text-muted-foreground">{t(title)}</span>
				<span className="text-[13px] text-muted-foreground">{t(body)}</span>
			</div>
			<span className="flex-none rounded-full border border-gold px-2.5 py-0.5 text-xs font-semibold text-gold">
				{t("landing.soon")}
			</span>
		</div>
	);
}

function DataRow({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex justify-between gap-3 border-t border-border pt-3 text-sm">
			<span className="text-muted-foreground">{label}</span>
			<span className="font-semibold tracking-wide tabular-nums">{value}</span>
		</div>
	);
}

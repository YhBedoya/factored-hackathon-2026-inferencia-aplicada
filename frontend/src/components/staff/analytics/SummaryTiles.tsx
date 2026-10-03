import type { ReactNode } from "react";

import type { AnalyticsSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatAvg, formatPercent, formatRatio, formatUsd } from "./format";
import { InfoHint } from "./InfoHint";

interface SummaryTilesProps {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

function Tile({
	testId,
	label,
	info,
	value,
	detail,
}: {
	testId: string;
	label: string;
	info: string;
	value: ReactNode;
	detail?: ReactNode;
}) {
	return (
		<div
			data-testid={testId}
			className="rounded-lg bg-card px-3 py-2 ring-1 ring-foreground/10"
		>
			<p className="flex items-center gap-1 text-xs text-muted-foreground">
				{label}
				<InfoHint label={label} text={info} />
			</p>
			<p className="text-xl font-semibold leading-tight">{value}</p>
			{detail !== undefined && (
				<p className="text-xs text-muted-foreground">{detail}</p>
			)}
		</div>
	);
}

/** The six headline tiles (D2): counts, rates with their ratio, averages. */
export function SummaryTiles({
	summary,
	isLoading,
	isError,
}: SummaryTilesProps) {
	const { t } = useI18n();
	const tiles = summary?.tiles;

	// The strip has no card of its own, so its loading, error and empty
	// states are a plain line instead of a BlockFrame body.
	if (isLoading || isError || tiles === undefined || tiles.interactions === 0) {
		let state = t("staff.analytics.state.empty");
		if (isLoading) {
			state = t("staff.analytics.state.loading");
		} else if (isError) {
			state = t("staff.analytics.state.error");
		}
		return (
			<p
				data-testid="analytics-tiles"
				className="text-sm text-muted-foreground"
			>
				{state}
			</p>
		);
	}

	return (
		<div
			data-testid="analytics-tiles"
			className="grid grid-cols-3 gap-3 lg:grid-cols-6"
		>
			<Tile
				testId="analytics-tile-interactions"
				label={t("staff.analytics.tile.interactions")}
				info={t("staff.analytics.info.tile.interactions")}
				value={tiles.interactions}
			/>
			<Tile
				testId="analytics-tile-resolution"
				label={t("staff.analytics.tile.resolution")}
				info={t("staff.analytics.info.tile.resolution")}
				value={formatPercent(tiles.resolution.rate)}
				detail={formatRatio(tiles.resolution.num, tiles.resolution.den)}
			/>
			<Tile
				testId="analytics-tile-escalation"
				label={t("staff.analytics.tile.escalation")}
				info={t("staff.analytics.info.tile.escalation")}
				value={formatPercent(tiles.escalation.rate)}
				detail={formatRatio(tiles.escalation.num, tiles.escalation.den)}
			/>
			<Tile
				testId="analytics-tile-cost"
				label={t("staff.analytics.tile.cost")}
				info={t("staff.analytics.info.tile.cost")}
				value={formatUsd(tiles.cost_per_interaction.avg_usd)}
				detail={tiles.cost_per_interaction.count}
			/>
			<Tile
				testId="analytics-tile-messages"
				label={t("staff.analytics.tile.messages")}
				info={t("staff.analytics.info.tile.messages")}
				value={formatAvg(tiles.messages_per_interaction.avg)}
				detail={tiles.messages_per_interaction.count}
			/>
			<Tile
				testId="analytics-tile-negative"
				label={t("staff.analytics.tile.negative")}
				info={t("staff.analytics.info.tile.negative")}
				value={formatPercent(tiles.negative_sentiment.rate)}
				detail={formatRatio(
					tiles.negative_sentiment.num,
					tiles.negative_sentiment.den,
				)}
			/>
		</div>
	);
}

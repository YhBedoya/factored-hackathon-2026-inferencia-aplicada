import type { ReactNode } from "react";

import type { AnalyticsSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { BlockFrame } from "./BlockFrame";
import { formatAvg, formatPercent, formatRatio, formatUsd } from "./format";

interface SummaryTilesProps {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

function Tile({
	testId,
	label,
	value,
	detail,
}: {
	testId: string;
	label: string;
	value: ReactNode;
	detail?: ReactNode;
}) {
	return (
		<div data-testid={testId} className="rounded-lg border p-3">
			<p className="text-xs text-muted-foreground">{label}</p>
			<p className="text-2xl font-semibold">{value}</p>
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

	return (
		<BlockFrame
			title={t("staff.analytics.tiles.title")}
			testId="analytics-tiles"
			isLoading={isLoading}
			isError={isError}
			isEmpty={tiles === undefined || tiles.interactions === 0}
		>
			{tiles && (
				<div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
					<Tile
						testId="analytics-tile-interactions"
						label={t("staff.analytics.tile.interactions")}
						value={tiles.interactions}
					/>
					<Tile
						testId="analytics-tile-resolution"
						label={t("staff.analytics.tile.resolution")}
						value={formatPercent(tiles.resolution.rate)}
						detail={formatRatio(tiles.resolution.num, tiles.resolution.den)}
					/>
					<Tile
						testId="analytics-tile-escalation"
						label={t("staff.analytics.tile.escalation")}
						value={formatPercent(tiles.escalation.rate)}
						detail={formatRatio(tiles.escalation.num, tiles.escalation.den)}
					/>
					<Tile
						testId="analytics-tile-cost"
						label={t("staff.analytics.tile.cost")}
						value={formatUsd(tiles.cost_per_interaction.avg_usd)}
						detail={tiles.cost_per_interaction.count}
					/>
					<Tile
						testId="analytics-tile-messages"
						label={t("staff.analytics.tile.messages")}
						value={formatAvg(tiles.messages_per_interaction.avg)}
						detail={tiles.messages_per_interaction.count}
					/>
					<Tile
						testId="analytics-tile-negative"
						label={t("staff.analytics.tile.negative")}
						value={formatPercent(tiles.negative_sentiment.rate)}
						detail={formatRatio(
							tiles.negative_sentiment.num,
							tiles.negative_sentiment.den,
						)}
					/>
				</div>
			)}
		</BlockFrame>
	);
}

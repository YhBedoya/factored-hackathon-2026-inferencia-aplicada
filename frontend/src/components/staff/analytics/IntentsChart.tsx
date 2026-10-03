import { useState } from "react";

import type { AnalyticsSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

import { BlockFrame } from "./BlockFrame";
import { formatPercent, formatRatio } from "./format";

interface Props {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

type IntentRow = AnalyticsSummary["intents"][number];
type SortKey = "count" | "rate";
type SortDir = "desc" | "asc";

// Intent | frequency bar | resolution-rate bar, one row per intent on a shared
// axis, as plain data bars: a chart can't keep two bar columns row-aligned
// while the rows re-sort. The longest bar takes 80% of its cell; the rest is
// the value, formatted in code (R4). The resolution count rides in the cell's
// tooltip, so every rate still carries its count (D11).
const GRID = "grid grid-cols-[minmax(0,9rem)_1fr_1fr] items-center gap-x-3";
const BAR_SHARE = 80;

function sortRows(rows: IntentRow[], key: SortKey, dir: SortDir): IntentRow[] {
	const sign = dir === "desc" ? -1 : 1;
	return [...rows].sort((a, b) => {
		if (key === "count") {
			return sign * (a.count - b.count);
		}
		// An intent with no resolvable segment has no rate; it sorts last either way.
		if (a.resolution.rate === null || b.resolution.rate === null) {
			return (
				(a.resolution.rate === null ? 1 : 0) -
				(b.resolution.rate === null ? 1 : 0)
			);
		}
		return sign * (a.resolution.rate - b.resolution.rate);
	});
}

function DataBar({
	share,
	color,
	value,
	title,
}: {
	share: number | null;
	color: string;
	value: string;
	title?: string;
}) {
	return (
		<div className="flex min-w-0 items-center gap-1.5" title={title}>
			{share !== null && (
				<div
					className="h-3 shrink-0 rounded-sm"
					style={{ width: `${share * BAR_SHARE}%`, background: color }}
				/>
			)}
			<span className="shrink-0 text-[10px] tabular-nums text-foreground">
				{value}
			</span>
		</div>
	);
}

export function IntentsChart({ summary, isLoading, isError }: Props) {
	const { t } = useI18n();
	const [sortKey, setSortKey] = useState<SortKey>("count");
	const [sortDir, setSortDir] = useState<SortDir>("desc");
	const intents = summary?.intents ?? [];
	const maxCount = Math.max(1, ...intents.map((row) => row.count));
	const rows = sortRows(intents, sortKey, sortDir);

	function sortBy(key: SortKey) {
		if (key === sortKey) {
			setSortDir(sortDir === "desc" ? "asc" : "desc");
		} else {
			setSortKey(key);
			setSortDir("desc");
		}
	}

	function header(key: SortKey, label: string) {
		const active = key === sortKey;
		return (
			<button
				type="button"
				onClick={() => sortBy(key)}
				aria-pressed={active}
				className={cn(
					"text-left hover:text-foreground",
					active && "font-medium text-foreground",
				)}
			>
				{label}
				{active && (sortDir === "desc" ? " ▼" : " ▲")}
			</button>
		);
	}

	return (
		<BlockFrame
			title={t("staff.analytics.chart.intents")}
			info={t("staff.analytics.info.chart.intents")}
			testId="analytics-chart-intents"
			isLoading={isLoading}
			isError={isError}
			isEmpty={intents.length === 0}
		>
			<div className="flex h-full min-h-0 flex-col text-xs">
				<div className={cn(GRID, "border-b pb-1 text-muted-foreground")}>
					<span>{t("staff.analytics.intents.intent")}</span>
					{header("count", t("staff.analytics.intents.volume"))}
					{header("rate", t("staff.analytics.intents.resolution"))}
				</div>
				<div className="flex min-h-0 flex-1 flex-col">
					{rows.map((row) => (
						<div
							key={row.intent}
							className={cn(GRID, "max-h-7 min-h-0 flex-1")}
						>
							<span
								className="truncate text-[10px] text-muted-foreground"
								title={row.intent}
							>
								{row.intent}
							</span>
							<DataBar
								share={row.count / maxCount}
								color="var(--chart-4)"
								value={String(row.count)}
							/>
							<DataBar
								share={row.resolution.rate}
								color="var(--chart-1)"
								value={formatPercent(row.resolution.rate)}
								title={formatRatio(row.resolution.num, row.resolution.den)}
							/>
						</div>
					))}
				</div>
			</div>
		</BlockFrame>
	);
}

import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";

import {
	type ChartConfig,
	ChartContainer,
	ChartTooltip,
	ChartTooltipContent,
} from "@/components/ui/chart";
import type { AnalyticsSummary } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

import { BlockFrame } from "./BlockFrame";
import { formatSeconds } from "./format";

interface Props {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

// One-line tick: a wrapped label runs its words together on a narrow axis.
// The tooltip carries the full text.
function SingleLineTick({
	x,
	y,
	payload,
}: {
	x?: number;
	y?: number;
	payload?: { value: string };
}) {
	const name = payload?.value ?? "";
	return (
		<text
			x={x}
			y={y}
			dy={3}
			textAnchor="end"
			className="fill-muted-foreground text-[10px]"
		>
			{name.length > 11 ? `${name.slice(0, 10)}…` : name}
		</text>
	);
}

interface CountBarsProps {
	title: string;
	data: { name: string; count: number }[];
	color: string;
	testId: string;
}

function CountBars({ title, data, color, testId }: CountBarsProps) {
	const config: ChartConfig = { count: { label: title, color } };
	return (
		<div data-testid={testId} className="flex min-h-0 flex-col">
			<h4 className="mb-1 text-xs font-medium">{title}</h4>
			<ChartContainer
				config={config}
				className="aspect-auto min-h-0 w-full flex-1"
			>
				<BarChart data={data} layout="vertical" margin={{ right: 24 }}>
					<XAxis type="number" hide />
					<YAxis
						type="category"
						dataKey="name"
						tickLine={false}
						axisLine={false}
						width={72}
						interval={0}
						tick={<SingleLineTick />}
					/>
					<ChartTooltip content={<ChartTooltipContent />} />
					<Bar dataKey="count" fill="var(--color-count)" radius={3}>
						<LabelList
							dataKey="count"
							position="right"
							fontSize={10}
							fill="var(--foreground)"
						/>
					</Bar>
				</BarChart>
			</ChartContainer>
		</div>
	);
}

export function EscalationsChart({ summary, isLoading, isError }: Props) {
	const { t } = useI18n();
	const esc = summary?.escalations;
	const unknown = t("staff.analytics.escalations.unknown");

	const byCause = (esc?.by_cause_group ?? []).map((row) => ({
		name:
			row.group === null
				? unknown
				: t(`staff.analytics.cause.${row.group}` as TKey),
		count: row.count,
	}));
	const byQueue = (esc?.by_queue ?? []).map((row) => ({
		name: row.queue === null ? unknown : t(`staff.queue.${row.queue}` as TKey),
		count: row.count,
	}));

	return (
		<BlockFrame
			title={t("staff.analytics.chart.escalations")}
			info={t("staff.analytics.info.chart.escalations")}
			testId="analytics-chart-escalations"
			isLoading={isLoading}
			isError={isError}
			isEmpty={byCause.length === 0 && byQueue.length === 0}
		>
			<div className="flex h-full min-h-0 flex-col gap-2">
				<p className="text-xs text-muted-foreground">
					{t("staff.analytics.escalations.median_claim")}:{" "}
					<span data-testid="analytics-escalations-median">
						{formatSeconds(esc?.time_to_claim_median_s ?? null)}
					</span>{" "}
					({esc?.time_to_claim_count ?? 0})
				</p>
				<div className="grid min-h-0 flex-1 grid-cols-2 gap-2">
					<CountBars
						title={t("staff.analytics.escalations.by_cause_group")}
						data={byCause}
						color="var(--chart-2)"
						testId="analytics-escalations-by-cause"
					/>
					<CountBars
						title={t("staff.analytics.escalations.by_queue")}
						data={byQueue}
						color="var(--chart-3)"
						testId="analytics-escalations-by-queue"
					/>
				</div>
			</div>
		</BlockFrame>
	);
}

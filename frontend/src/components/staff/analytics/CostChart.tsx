import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { BlockFrame } from "@/components/staff/analytics/BlockFrame";
import { formatUsd, formatUsdTick } from "@/components/staff/analytics/format";
import {
	type ChartConfig,
	ChartContainer,
	ChartLegend,
	ChartLegendContent,
	ChartTooltip,
	ChartTooltipContent,
} from "@/components/ui/chart";
import type { AnalyticsSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface CostChartProps {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

interface FigureProps {
	label: string;
	value: string;
	hint?: string;
	testId: string;
}

function Figure({ label, value, hint, testId }: FigureProps) {
	return (
		<span data-testid={testId} className="text-muted-foreground">
			{label}: <span className="font-semibold text-foreground">{value}</span>
			{hint && ` (${hint})`}
		</span>
	);
}

export function CostChart({ summary, isLoading, isError }: CostChartProps) {
	const { t } = useI18n();
	const cost = summary?.cost;

	const config: ChartConfig = {
		nlu_usd: {
			label: t("staff.analytics.cost.nlu"),
			color: "var(--chart-1)",
		},
		compose_usd: {
			label: t("staff.analytics.cost.compose"),
			color: "var(--chart-4)",
		},
		agent_usd: {
			label: t("staff.analytics.cost.agent"),
			color: "var(--chart-2)",
		},
		handoff_summary_usd: {
			label: t("staff.analytics.cost.handoff_summary"),
			color: "var(--chart-3)",
		},
	};

	const isEmpty =
		!cost || (cost.total_usd === 0 && cost.sentiment_overhead_usd === 0);

	return (
		<BlockFrame
			title={t("staff.analytics.chart.cost")}
			info={t("staff.analytics.info.chart.cost")}
			testId="analytics-chart-cost"
			isLoading={isLoading}
			isError={isError}
			isEmpty={isEmpty}
		>
			{cost && (
				<div className="flex h-full min-h-0 flex-col gap-2">
					{/* D12: scoring overhead is shown apart, never added to the totals. */}
					<div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
						<Figure
							testId="analytics-cost-total"
							label={t("staff.analytics.cost.total")}
							value={formatUsd(cost.total_usd)}
						/>
						<Figure
							testId="analytics-cost-per-resolved"
							label={t("staff.analytics.cost.per_resolved")}
							value={formatUsd(cost.per_resolved.usd)}
							hint={`n = ${cost.per_resolved.resolved}`}
						/>
						<span className="border-l pl-4">
							<Figure
								testId="analytics-cost-sentiment-overhead"
								label={t("staff.analytics.cost.sentiment_overhead")}
								value={formatUsd(cost.sentiment_overhead_usd)}
							/>
						</span>
					</div>
					<ChartContainer
						config={config}
						className="aspect-auto min-h-0 w-full flex-1"
					>
						<BarChart data={cost.per_day} accessibilityLayer>
							<CartesianGrid vertical={false} />
							<XAxis
								dataKey="day"
								tickLine={false}
								axisLine={false}
								tickFormatter={(day: string) => day.slice(5)}
								minTickGap={16}
							/>
							<YAxis
								width={48}
								tickLine={false}
								axisLine={false}
								tick={{ fontSize: 10 }}
								tickFormatter={formatUsdTick}
								label={{
									value: t("staff.analytics.cost.axis"),
									angle: -90,
									position: "insideLeft",
									style: { textAnchor: "middle", fontSize: 10 },
									fill: "var(--muted-foreground)",
								}}
							/>
							<ChartTooltip
								content={
									<ChartTooltipContent
										formatter={(value, name) => (
											<span>
												{config[String(name)]?.label}:{" "}
												{formatUsd(Number(value))}
											</span>
										)}
									/>
								}
							/>
							<ChartLegend
								content={
									<ChartLegendContent className="flex-wrap gap-x-2 gap-y-0 pt-1 text-[10px]" />
								}
							/>
							{Object.keys(config).map((key) => (
								<Bar
									key={key}
									dataKey={key}
									stackId="cost"
									fill={`var(--color-${key})`}
								/>
							))}
						</BarChart>
					</ChartContainer>
				</div>
			)}
		</BlockFrame>
	);
}

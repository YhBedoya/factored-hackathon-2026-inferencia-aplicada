import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";

import { BlockFrame } from "@/components/staff/analytics/BlockFrame";
import { formatUsd } from "@/components/staff/analytics/format";
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
		<div data-testid={testId}>
			<p className="text-xs text-muted-foreground">{label}</p>
			<p className="text-lg font-semibold">{value}</p>
			{hint && <p className="text-xs text-muted-foreground">{hint}</p>}
		</div>
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
			testId="analytics-chart-cost"
			isLoading={isLoading}
			isError={isError}
			isEmpty={isEmpty}
		>
			{cost && (
				<div className="space-y-4">
					<div className="flex flex-wrap gap-6">
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
					</div>
					<ChartContainer config={config} className="h-56 w-full">
						<BarChart data={cost.per_day} accessibilityLayer>
							<CartesianGrid vertical={false} />
							<XAxis dataKey="day" tickLine={false} axisLine={false} />
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
							<ChartLegend content={<ChartLegendContent />} />
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
					{/* D12: scoring overhead is shown apart, never added to the totals. */}
					<div className="border-t pt-3">
						<Figure
							testId="analytics-cost-sentiment-overhead"
							label={t("staff.analytics.cost.sentiment_overhead")}
							value={formatUsd(cost.sentiment_overhead_usd)}
						/>
					</div>
				</div>
			)}
		</BlockFrame>
	);
}

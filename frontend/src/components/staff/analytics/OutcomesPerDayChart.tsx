import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
	type ChartConfig,
	ChartContainer,
	ChartLegend,
	ChartLegendContent,
	ChartTooltip,
	ChartTooltipContent,
} from "@/components/ui/chart";
import type { AnalyticsSummary } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

import { BlockFrame } from "./BlockFrame";

// D1 order: the stack bottom is the first bucket.
const OUTCOMES = [
	{ key: "escalated", color: "var(--chart-2)" },
	{ key: "resolved", color: "var(--chart-1)" },
	{ key: "abandoned", color: "var(--chart-4)" },
	{ key: "abstained", color: "var(--chart-5)" },
	{ key: "other", color: "var(--chart-5)" },
] as const;

interface Props {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

export function OutcomesPerDayChart({ summary, isLoading, isError }: Props) {
	const { t } = useI18n();
	const perDay = summary?.per_day ?? [];
	const isEmpty = perDay.every((d) =>
		OUTCOMES.every(({ key }) => d[key] === 0),
	);

	const config: ChartConfig = {};
	for (const { key, color } of OUTCOMES) {
		config[key] = {
			label: t(`staff.analytics.outcome.${key}` as TKey),
			color,
		};
	}

	return (
		<BlockFrame
			title={t("staff.analytics.chart.per_day")}
			testId="analytics-chart-per-day"
			isLoading={isLoading}
			isError={isError}
			isEmpty={isEmpty}
		>
			<ChartContainer config={config} className="min-h-[240px] w-full">
				<BarChart data={perDay}>
					<CartesianGrid vertical={false} />
					<XAxis dataKey="day" tickLine={false} axisLine={false} />
					<YAxis allowDecimals={false} width={32} />
					<ChartTooltip content={<ChartTooltipContent />} />
					<ChartLegend content={<ChartLegendContent />} />
					{OUTCOMES.map(({ key }) => (
						<Bar
							key={key}
							dataKey={key}
							stackId="outcome"
							fill={`var(--color-${key})`}
						/>
					))}
				</BarChart>
			</ChartContainer>
		</BlockFrame>
	);
}

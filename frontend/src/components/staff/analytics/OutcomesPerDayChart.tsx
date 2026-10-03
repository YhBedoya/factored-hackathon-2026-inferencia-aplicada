import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

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

// D1 buckets, one line each. They are exclusive, so on any day they add up
// to the Total line drawn over them.
const OUTCOMES = [
	{ key: "escalated", color: "var(--chart-2)" },
	{ key: "resolved", color: "var(--chart-1)" },
	{ key: "abandoned", color: "var(--chart-3)" },
	{ key: "abstained", color: "var(--chart-4)" },
	{ key: "other", color: "var(--chart-5)" },
] as const;

// "2026-10-02" -> "10-02": the year is noise on a 7 to 92 day axis.
function shortDay(day: string): string {
	return day.slice(5);
}

interface Props {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

export function OutcomesPerDayChart({ summary, isLoading, isError }: Props) {
	const { t } = useI18n();
	const perDay = summary?.per_day ?? [];
	const data = perDay.map((d) => ({
		...d,
		total: OUTCOMES.reduce((sum, { key }) => sum + d[key], 0),
	}));
	const isEmpty = data.every((d) => d.total === 0);

	const config: ChartConfig = {
		total: {
			label: t("staff.analytics.outcome.total"),
			color: "var(--foreground)",
		},
	};
	for (const { key, color } of OUTCOMES) {
		config[key] = {
			label: t(`staff.analytics.outcome.${key}` as TKey),
			color,
		};
	}

	return (
		<BlockFrame
			title={t("staff.analytics.chart.per_day")}
			info={t("staff.analytics.info.chart.per_day")}
			testId="analytics-chart-per-day"
			isLoading={isLoading}
			isError={isError}
			isEmpty={isEmpty}
		>
			<ChartContainer
				config={config}
				className="aspect-auto h-full min-h-0 w-full"
			>
				<LineChart data={data} margin={{ top: 8, right: 8 }}>
					<CartesianGrid vertical={false} />
					<XAxis
						dataKey="day"
						tickLine={false}
						axisLine={false}
						tickFormatter={shortDay}
						minTickGap={16}
					/>
					<YAxis allowDecimals={false} width={28} />
					<ChartTooltip content={<ChartTooltipContent />} />
					<ChartLegend
						content={
							<ChartLegendContent className="flex-wrap gap-x-2 gap-y-0 pt-1 text-[10px]" />
						}
					/>
					{Object.keys(config).map((key) => (
						<Line
							key={key}
							dataKey={key}
							type="linear"
							stroke={`var(--color-${key})`}
							strokeWidth={key === "total" ? 2.5 : 1.5}
							dot={{ r: 2.5, fill: `var(--color-${key})`, strokeWidth: 0 }}
							activeDot={{ r: 4 }}
						/>
					))}
				</LineChart>
			</ChartContainer>
		</BlockFrame>
	);
}

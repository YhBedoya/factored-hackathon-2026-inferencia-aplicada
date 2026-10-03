import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";

import { BlockFrame } from "@/components/staff/analytics/BlockFrame";
import { formatPercent } from "@/components/staff/analytics/format";
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

interface SentimentChartProps {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

interface SplitProps {
	label: string;
	scored: number;
	row: Record<string, number>;
	config: ChartConfig;
}

// A partition's share of the scored rows, centred on it. Hidden when the
// partition is too narrow to hold the text; the tooltip still has the count.
const MIN_LABEL_WIDTH = 32;

function ShareLabel({
	x,
	y,
	width,
	height,
	value,
	scored,
}: {
	x?: number | string;
	y?: number | string;
	width?: number | string;
	height?: number | string;
	value?: number | string;
	scored: number;
}) {
	const w = Number(width);
	if (scored === 0 || !(w >= MIN_LABEL_WIDTH)) {
		return null;
	}
	return (
		<text
			x={Number(x) + w / 2}
			y={Number(y) + Number(height) / 2}
			dy={3}
			textAnchor="middle"
			fontSize={10}
			fill="var(--background)"
		>
			{formatPercent(Number(value) / scored)}
		</text>
	);
}

/** One stacked horizontal bar: a single row split across the config keys. */
function Split({ label, scored, row, config }: SplitProps) {
	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<p className="text-xs font-medium">
				{label} (n = {scored})
			</p>
			<ChartContainer
				config={config}
				className="aspect-auto min-h-0 w-full flex-1"
			>
				<BarChart data={[row]} layout="vertical" accessibilityLayer>
					<XAxis type="number" hide />
					<YAxis type="category" dataKey="name" hide />
					<ChartTooltip content={<ChartTooltipContent hideLabel />} />
					<ChartLegend
						content={
							<ChartLegendContent className="flex-wrap gap-x-2 gap-y-0 pt-1 text-[10px]" />
						}
					/>
					{Object.keys(config).map((key) => (
						<Bar
							key={key}
							dataKey={key}
							stackId="split"
							fill={`var(--color-${key})`}
						>
							<LabelList
								dataKey={key}
								content={<ShareLabel scored={scored} />}
							/>
						</Bar>
					))}
				</BarChart>
			</ChartContainer>
		</div>
	);
}

export function SentimentChart({
	summary,
	isLoading,
	isError,
}: SentimentChartProps) {
	const { t } = useI18n();
	const sentiment = summary?.sentiment;

	const overallConfig: ChartConfig = {
		negative: {
			label: t("staff.analytics.sentiment.negative"),
			color: "var(--chart-2)",
		},
		neutral: {
			label: t("staff.analytics.sentiment.neutral"),
			color: "var(--chart-3)",
		},
		positive: {
			label: t("staff.analytics.sentiment.positive"),
			color: "var(--chart-1)",
		},
	};
	const trajectoryConfig: ChartConfig = {
		better: {
			label: t("staff.analytics.sentiment.better"),
			color: "var(--chart-1)",
		},
		same: {
			label: t("staff.analytics.sentiment.same"),
			color: "var(--chart-3)",
		},
		worse: {
			label: t("staff.analytics.sentiment.worse"),
			color: "var(--chart-2)",
		},
	};

	const isEmpty =
		!sentiment ||
		(sentiment.overall.scored === 0 && sentiment.trajectory.scored === 0);

	return (
		<BlockFrame
			title={t("staff.analytics.chart.sentiment")}
			info={t("staff.analytics.info.chart.sentiment")}
			testId="analytics-chart-sentiment"
			isLoading={isLoading}
			isError={isError}
			isEmpty={isEmpty}
		>
			{sentiment && (
				<div className="flex h-full min-h-0 flex-col gap-2">
					<Split
						label={t("staff.analytics.sentiment.overall")}
						scored={sentiment.overall.scored}
						row={{
							name: 0,
							negative: sentiment.overall.negative,
							neutral: sentiment.overall.neutral,
							positive: sentiment.overall.positive,
						}}
						config={overallConfig}
					/>
					<Split
						label={t("staff.analytics.sentiment.trajectory")}
						scored={sentiment.trajectory.scored}
						row={{
							name: 0,
							better: sentiment.trajectory.better,
							same: sentiment.trajectory.same,
							worse: sentiment.trajectory.worse,
						}}
						config={trajectoryConfig}
					/>
				</div>
			)}
		</BlockFrame>
	);
}

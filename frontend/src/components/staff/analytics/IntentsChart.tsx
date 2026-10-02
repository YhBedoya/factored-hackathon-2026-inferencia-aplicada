import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";

import {
	type ChartConfig,
	ChartContainer,
	ChartTooltip,
	ChartTooltipContent,
} from "@/components/ui/chart";
import type { AnalyticsSummary } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { BlockFrame } from "./BlockFrame";
import { formatPercent, formatRatio } from "./format";

interface Props {
	summary: AnalyticsSummary | undefined;
	isLoading: boolean;
	isError: boolean;
}

const ROW_HEIGHT = 32;

export function IntentsChart({ summary, isLoading, isError }: Props) {
	const { t } = useI18n();
	const intents = summary?.intents ?? [];
	const volume = t("staff.analytics.intents.volume");
	const resolution = t("staff.analytics.intents.resolution");

	const config: ChartConfig = {
		count: { label: volume, color: "var(--chart-1)" },
	};
	// The resolution sits next to its bar as a label built in code (R4).
	const data = intents.map((row) => ({
		intent: row.intent,
		count: row.count,
		label: `${row.count} · ${resolution} ${formatPercent(row.resolution.rate)} (${formatRatio(row.resolution.num, row.resolution.den)})`,
	}));

	return (
		<BlockFrame
			title={t("staff.analytics.chart.intents")}
			testId="analytics-chart-intents"
			isLoading={isLoading}
			isError={isError}
			isEmpty={intents.length === 0}
		>
			<ChartContainer
				config={config}
				className="w-full"
				style={{ height: Math.max(data.length * ROW_HEIGHT, 120) }}
			>
				<BarChart data={data} layout="vertical" margin={{ right: 190 }}>
					<XAxis type="number" hide />
					<YAxis
						type="category"
						dataKey="intent"
						tickLine={false}
						axisLine={false}
						width={140}
					/>
					<ChartTooltip content={<ChartTooltipContent />} />
					<Bar dataKey="count" fill="var(--color-count)" radius={3}>
						<LabelList
							dataKey="label"
							position="right"
							className="fill-foreground text-xs"
						/>
					</Bar>
				</BarChart>
			</ChartContainer>
		</BlockFrame>
	);
}

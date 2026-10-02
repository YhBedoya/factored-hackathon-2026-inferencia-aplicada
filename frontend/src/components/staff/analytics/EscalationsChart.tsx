import { Bar, BarChart, XAxis, YAxis } from "recharts";

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

interface CountBarsProps {
	title: string;
	data: { name: string; count: number }[];
	color: string;
	testId: string;
}

function CountBars({ title, data, color, testId }: CountBarsProps) {
	const config: ChartConfig = { count: { label: title, color } };
	return (
		<div data-testid={testId}>
			<h4 className="mb-1 text-sm font-medium">{title}</h4>
			<ChartContainer
				config={config}
				className="w-full"
				style={{ height: Math.max(data.length * 32, 80) }}
			>
				<BarChart data={data} layout="vertical">
					<XAxis type="number" hide />
					<YAxis
						type="category"
						dataKey="name"
						tickLine={false}
						axisLine={false}
						width={140}
					/>
					<ChartTooltip content={<ChartTooltipContent />} />
					<Bar dataKey="count" fill="var(--color-count)" radius={3} />
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
			testId="analytics-chart-escalations"
			isLoading={isLoading}
			isError={isError}
			isEmpty={byCause.length === 0 && byQueue.length === 0}
		>
			<div className="space-y-4">
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
				<p className="text-sm text-muted-foreground">
					{t("staff.analytics.escalations.median_claim")}:{" "}
					<span data-testid="analytics-escalations-median">
						{formatSeconds(esc?.time_to_claim_median_s ?? null)}
					</span>{" "}
					({esc?.time_to_claim_count ?? 0})
				</p>
			</div>
		</BlockFrame>
	);
}

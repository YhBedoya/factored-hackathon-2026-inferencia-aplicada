import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { InfoHint } from "./InfoHint";

const STATE_TEXT = "text-sm text-muted-foreground";

interface BlockFrameProps {
	title: string;
	/** How to read the panel, shown behind the ⓘ next to the title. */
	info: string;
	testId: string;
	isLoading: boolean;
	isError: boolean;
	isEmpty: boolean;
	className?: string;
	children: ReactNode;
}

/** A titled card that fills its grid cell; its body is the loading, error or empty state, else its children. */
export function BlockFrame({
	title,
	info,
	testId,
	isLoading,
	isError,
	isEmpty,
	className,
	children,
}: BlockFrameProps) {
	const { t } = useI18n();

	let body: ReactNode = children;
	if (isLoading) {
		body = (
			<p data-testid="analytics-block-loading" className={STATE_TEXT}>
				{t("staff.analytics.state.loading")}
			</p>
		);
	} else if (isError) {
		body = (
			<p data-testid="analytics-block-error" className={STATE_TEXT}>
				{t("staff.analytics.state.error")}
			</p>
		);
	} else if (isEmpty) {
		body = (
			<p data-testid="analytics-block-empty" className={STATE_TEXT}>
				{t("staff.analytics.state.empty")}
			</p>
		);
	}

	return (
		<Card
			size="sm"
			data-testid={testId}
			className={cn("flex h-full min-h-0 flex-col", className)}
		>
			<CardHeader>
				<CardTitle className="flex items-center gap-1 text-sm">
					{title}
					<InfoHint label={title} text={info} />
				</CardTitle>
			</CardHeader>
			<CardContent className="min-h-0 flex-1">{body}</CardContent>
		</Card>
	);
}

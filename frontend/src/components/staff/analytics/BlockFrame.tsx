import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

const STATE_TEXT = "text-sm text-muted-foreground";

interface BlockFrameProps {
	title: string;
	testId: string;
	isLoading: boolean;
	isError: boolean;
	isEmpty: boolean;
	children: ReactNode;
}

/** A titled card whose body is the loading, error or empty state, else its children. */
export function BlockFrame({
	title,
	testId,
	isLoading,
	isError,
	isEmpty,
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
		<Card data-testid={testId}>
			<CardHeader>
				<CardTitle>{title}</CardTitle>
			</CardHeader>
			<CardContent>{body}</CardContent>
		</Card>
	);
}

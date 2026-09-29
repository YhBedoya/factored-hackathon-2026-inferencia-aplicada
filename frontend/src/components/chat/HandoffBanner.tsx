import { Card, CardContent } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";
import type { HandoffBannerPayload } from "@/lib/sse";

type HandoffBannerProps = {
	payload: HandoffBannerPayload;
};

/**
 * `ui.handoff_banner`: the handoff just opened (D4-A D12) and, on the fraud
 * path, the claims opened before it (D4-B D9-D11). `reference`,
 * `queue_label` and every `case_ids` entry are code-formatted server-side
 * (R4); this only lays them out, never re-formats them.
 */
export function HandoffBanner({ payload }: HandoffBannerProps) {
	const { t } = useI18n();
	return (
		<Card
			data-testid="handoff-banner"
			className="mt-2 max-w-sm border border-cyan"
		>
			<CardContent className="flex flex-col gap-1">
				<p className="text-sm">
					{t("handoff.sent_to", { queue: payload.queue_label })}
				</p>
				<p className="text-sm" data-testid="handoff-reference">
					{payload.reference}
				</p>
				{payload.case_ids.length > 0 && (
					<ul className="text-sm text-muted-foreground">
						{payload.case_ids.map((caseId) => (
							<li key={caseId} data-testid="handoff-case-id">
								{caseId}
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}

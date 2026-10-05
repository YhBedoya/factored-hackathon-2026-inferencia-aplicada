import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import type { ConfirmationDecision } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import type { ConfirmPayload } from "@/lib/sse";

type ConfirmCardProps = {
	payload: ConfirmPayload;
	onDecide: (tokenId: string, decision: ConfirmationDecision) => void;
};

/**
 * `ui.confirm`: every plan step, gold-bordered (needs confirmation, brand.md).
 * Steps and `facts` values are shown exactly as the server sent them (R4):
 * only the step title is looked up in the dictionary, by `summary_key`.
 */
export function ConfirmCard({ payload, onDecide }: ConfirmCardProps) {
	const { t } = useI18n();
	const [disabled, setDisabled] = useState(false);
	const acceptDecline = payload.labels === "accept_decline";

	function handleDecide(decision: ConfirmationDecision) {
		setDisabled(true);
		onDecide(payload.token_id, decision);
	}

	return (
		<Card
			data-testid="confirm-card"
			className="mt-2 max-w-sm border border-gold"
		>
			<CardHeader>
				<CardTitle>{t("confirm.title")}</CardTitle>
			</CardHeader>
			<CardContent className="flex flex-col gap-3">
				{payload.steps.map((step) => (
					<div key={step.tool} data-testid="confirm-step">
						<p className="font-medium">
							{t(`confirm.steps.${step.summary_key}` as TKey)}
						</p>
						<ul className="text-sm text-muted-foreground">
							{step.facts.map((fact, index) => (
								// Index-qualified: an open-card plan repeats the key "profile_field".
								// biome-ignore lint/suspicious/noArrayIndexKey: facts are static per card
								<li key={`${fact.key}-${index}`}>{String(fact.value)}</li>
							))}
						</ul>
					</div>
				))}
			</CardContent>
			<CardFooter className="flex gap-2">
				<Button
					type="button"
					data-testid="confirm-accept"
					disabled={disabled}
					onClick={() => handleDecide("confirm")}
				>
					{t(acceptDecline ? "confirm.accept" : "confirm.confirm")}
				</Button>
				<Button
					type="button"
					variant="outline"
					data-testid="confirm-cancel"
					disabled={disabled}
					onClick={() => handleDecide("cancel")}
				>
					{t(acceptDecline ? "confirm.decline" : "confirm.cancel")}
				</Button>
			</CardFooter>
		</Card>
	);
}

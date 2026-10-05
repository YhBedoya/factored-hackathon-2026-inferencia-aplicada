import { useCallback, useEffect, useRef, useState } from "react";

import {
	type CardRequestDecision,
	type CardRequestPanel as CardRequestPanelData,
	decideCardRequestApiV1StaffHandoffsHandoffIdCardRequestDecisionPost,
	getCardRequestApiV1StaffHandoffsHandoffIdCardRequestGet,
} from "@/client";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type TKey, useI18n } from "@/lib/i18n";
import es from "@/lib/i18n/es.json";
import { newId } from "@/lib/uuid";

type Decision = CardRequestDecision["decision"];

// The five decline reasons T9 added; the server validates against policy.
const DECLINE_REASONS = [
	"low_credit_score",
	"insufficient_income",
	"high_existing_debt",
	"inconsistent_data",
	"other",
] as const;

// Error codes that have their own `staff.card_request.error.*` copy.
// `unknown_outcome` is client-side (5xx / no answer). The dialog stays open
// and a retry reuses the same Idempotency-Key, so it can't decide twice.
const KNOWN_ERRORS = new Set([
	"unknown_outcome",
	"limit_out_of_bounds",
	"limit_required",
	"balance_not_zero",
	"already_decided",
	"decline_reason_invalid",
]);

type Props = {
	handoffId: string;
	// Tells the page whether the request is still undecided, to gate "return".
	onPendingChange: (pending: boolean) => void;
};

const SECTION = "flex flex-col gap-2 border-t border-border pt-4";
const HEADING = "text-[13px] font-semibold text-muted-foreground";

function Row({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex justify-between gap-4 text-sm">
			<span className="text-muted-foreground">{label}</span>
			<span>{value}</span>
		</div>
	);
}

/**
 * The staff decision panel for a card request (D9-C, AS3). Everything shown
 * -- money, bounds, balance, masks -- is the server's string (R4); the only
 * client-side value is what the agent types as the credit limit, sent as-is
 * for the server to validate. The panel is claimant-only: the GET answers 404
 * to anyone else and then nothing renders.
 */
export function CardRequestPanel({ handoffId, onPendingChange }: Props) {
	const { t } = useI18n();
	const [panel, setPanel] = useState<CardRequestPanelData | null>(null);
	const [decision, setDecision] = useState<Decision | null>(null);
	// The opening's chosen decision; "Enviar" takes it to the review dialog.
	const [choice, setChoice] = useState<"approve" | "decline" | null>(null);
	const [limit, setLimit] = useState("");
	const [reason, setReason] = useState("");
	const [submitting, setSubmitting] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const [result, setResult] = useState<"verified" | "unverified" | null>(null);
	// One key per dialog: reused on a retry, so a double click or a network
	// retry can never make two decisions. A new dialog gets a fresh one.
	const idempotencyKey = useRef("");

	const load = useCallback(async () => {
		const response =
			await getCardRequestApiV1StaffHandoffsHandoffIdCardRequestGet({
				path: { handoff_id: handoffId },
			});
		if (response.error !== undefined || !response.data) {
			// 404 for a non-claimant: no panel, and the server gates return.
			onPendingChange(false);
			return;
		}
		setPanel(response.data);
		onPendingChange(response.data.request.status === "pending");
	}, [handoffId, onPendingChange]);

	useEffect(() => {
		void load();
	}, [load]);

	function openDialog(next: Decision) {
		idempotencyKey.current = newId();
		setErrorCode(null);
		setDecision(next);
	}

	function closeDialog() {
		if (!submitting) {
			setDecision(null);
		}
	}

	// The balance refusal wrote nothing, so the follow-up decision is a new
	// dialog with a new key.
	function switchToBalanceDecision() {
		openDialog("not_cancelled_balance");
	}

	async function confirm() {
		if (!decision) {
			return;
		}
		setSubmitting(true);
		setErrorCode(null);
		const body: CardRequestDecision = { decision };
		if (decision === "approve" && panel?.credit_bounds) {
			body.credit_limit = limit.trim();
		}
		if (decision === "decline") {
			body.decline_reason = reason;
		}
		try {
			const response =
				await decideCardRequestApiV1StaffHandoffsHandoffIdCardRequestDecisionPost(
					{
						path: { handoff_id: handoffId },
						headers: { "Idempotency-Key": idempotencyKey.current },
						body,
					},
				);
			if (response.error !== undefined || !response.data) {
				const detail = (response.error as { detail?: unknown } | undefined)
					?.detail;
				// 4xx: an explicit rejection, nothing was written. Anything else
				// (5xx, no response) may have committed: the outcome is unknown.
				const status = response.response?.status ?? 0;
				const rejected = status >= 400 && status < 500;
				setErrorCode(
					rejected
						? typeof detail === "string"
							? detail
							: "generic"
						: "unknown_outcome",
				);
				return;
			}
			setResult(response.data.verified ? "verified" : "unverified");
			setDecision(null);
			await load();
		} catch {
			// Network failure or timeout: the write may have landed.
			setErrorCode("unknown_outcome");
		} finally {
			setSubmitting(false);
		}
	}

	if (!panel) {
		return null;
	}

	const { request, customer, cards, credit_bounds, close_balance_display } =
		panel;
	const pending = request.status === "pending";
	const isCreditOpen =
		request.kind === "open" && request.card_kind === "credit";
	const approveBlocked = isCreditOpen && limit.trim() === "";
	const declineBlocked = reason === "";
	const confirmBlocked =
		(decision === "approve" && approveBlocked) ||
		(decision === "decline" && declineBlocked);
	const sendBlocked =
		choice === null ||
		(choice === "approve" && approveBlocked) ||
		(choice === "decline" && declineBlocked);
	const errorKey = (
		errorCode && KNOWN_ERRORS.has(errorCode) ? errorCode : "generic"
	) as string;

	// Statuses outside the four the dictionary knows are shown as the server sent them.
	function cardStatus(status: string): string {
		const key = `home.cards.status.${status}`;
		return key in es ? t(key as TKey) : status;
	}

	return (
		<section
			className="flex flex-col gap-3 rounded-2xl bg-card p-4"
			data-testid="card-request-panel"
		>
			<header className="flex items-center justify-between gap-2">
				<h3 className="text-sm font-semibold">
					{t("staff.card_request.title")}
				</h3>
				<span
					className="text-xs text-muted-foreground"
					data-testid="card-request-status"
				>
					{t(`staff.card_request.status.${request.status}` as TKey)}
				</span>
			</header>
			<div className="flex flex-col gap-1.5">
				<Row
					label={t("staff.card_request.reference")}
					value={request.reference}
				/>
				<Row
					label={t(`staff.card_request.kind.${request.kind}` as TKey)}
					value={[
						t(`home.cards.kind.${request.card_kind}` as TKey),
						request.card_mask,
					]
						.filter(Boolean)
						.join(" ")}
				/>
				{request.reason_code && (
					// Translated here, in the staff UI language, not the
					// customer's (`reason_label` follows the conversation).
					<Row
						label={t("staff.card_request.close_reason_label")}
						value={t(
							`staff.card_request.close_reason.${request.reason_code}` as TKey,
						)}
					/>
				)}
			</div>

			<div className={SECTION}>
				{customer.credit_score !== null && (
					<Row
						label={t("staff.card_request.credit_score")}
						value={String(customer.credit_score)}
					/>
				)}
				{customer.segment && (
					<Row
						label={t("staff.card_request.segment")}
						value={customer.segment}
					/>
				)}
				{customer.tenure_years !== null && (
					<Row
						label={t("staff.card_request.tenure")}
						value={String(customer.tenure_years)}
					/>
				)}
				{customer.occupation && (
					<Row
						label={t("staff.card_request.occupation")}
						value={customer.occupation}
					/>
				)}
				{customer.income_display && (
					<Row
						label={t("staff.card_request.income")}
						value={customer.income_display}
					/>
				)}
				{(customer.occupation_changed || customer.income_changed) && (
					<span
						className="w-fit rounded-full bg-muted px-2 py-0.5 text-xs font-semibold"
						data-testid="card-request-changed"
					>
						{t("staff.card_request.changed")}
					</span>
				)}
			</div>

			{cards.length > 0 && (
				<div className={SECTION}>
					<h4 className={HEADING}>{t("staff.card_request.cards")}</h4>
					<ul className="flex flex-col gap-1">
						{cards.map((card) => (
							<li key={card.mask} className="flex flex-col gap-0.5 text-sm">
								<span>
									{card.mask} · {t(`home.cards.kind.${card.kind}` as TKey)} ·{" "}
									{cardStatus(card.status)}
								</span>
								{/* Each amount carries its own label: a bare "a / b" was unreadable. */}
								<span className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
									{card.balance_display && (
										<span>
											{t(
												`staff.card_request.card_balance.${card.kind}` as TKey,
											)}
											:{" "}
											<span className="text-foreground">
												{card.balance_display}
											</span>
										</span>
									)}
									{card.credit_limit_display && (
										<span>
											{t("staff.card_request.credit_limit")}:{" "}
											<span className="text-foreground">
												{card.credit_limit_display}
											</span>
										</span>
									)}
								</span>
							</li>
						))}
					</ul>
				</div>
			)}

			{request.kind === "close" && close_balance_display && (
				<Row
					label={t("staff.card_request.close_balance")}
					value={close_balance_display}
				/>
			)}

			{!pending && request.decision && (
				<p
					className="text-sm font-semibold"
					data-testid="card-request-decision"
				>
					{t(`staff.card_request.decision.${request.decision}` as TKey)}
				</p>
			)}
			{result && (
				<p role="status" className="text-sm" data-testid="card-request-result">
					{t(`staff.card_request.result.${result}` as TKey)}
				</p>
			)}

			{pending && request.kind === "open" && (
				<div className={SECTION}>
					<fieldset className="flex flex-col gap-1.5">
						<legend className="mb-1.5 text-sm font-medium">
							{t("staff.card_request.decision_label")}
						</legend>
						<div className="flex gap-2">
							<Button
								variant={choice === "approve" ? "default" : "outline"}
								data-testid="card-request-approve"
								aria-pressed={choice === "approve"}
								onClick={() => setChoice("approve")}
							>
								{t("staff.card_request.decision.approve")}
							</Button>
							<Button
								variant={choice === "decline" ? "default" : "outline"}
								data-testid="card-request-decline"
								aria-pressed={choice === "decline"}
								onClick={() => setChoice("decline")}
							>
								{t("staff.card_request.decision.decline")}
							</Button>
						</div>
					</fieldset>
					{choice === "approve" && isCreditOpen && (
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="card-request-limit">
								{t("staff.card_request.credit_limit")}
							</Label>
							<Input
								id="card-request-limit"
								data-testid="card-request-limit"
								inputMode="decimal"
								value={limit}
								onChange={(event) => setLimit(event.target.value)}
							/>
							{credit_bounds && (
								<span className="text-xs text-muted-foreground">
									{t("staff.card_request.credit_bounds", {
										min: credit_bounds.min_display,
										max: credit_bounds.max_display,
									})}
								</span>
							)}
						</div>
					)}
					{choice === "decline" && (
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="card-request-reason">
								{t("staff.card_request.reason")}
							</Label>
							<select
								id="card-request-reason"
								data-testid="card-request-reason"
								className="h-8 rounded-lg border border-input bg-bg px-2 text-sm text-foreground [color-scheme:dark]"
								value={reason}
								onChange={(event) => setReason(event.target.value)}
							>
								<option value="" />
								{DECLINE_REASONS.map((code) => (
									<option key={code} value={code}>
										{t(`staff.card_request.decline_reason.${code}` as TKey)}
									</option>
								))}
							</select>
						</div>
					)}
					<Button
						className="w-fit"
						data-testid="card-request-send"
						disabled={sendBlocked}
						onClick={() => choice && openDialog(choice)}
					>
						{t("staff.card_request.send")}
					</Button>
				</div>
			)}

			{pending && request.kind === "close" && (
				<div className={`${SECTION} flex-row flex-wrap`}>
					<Button
						data-testid="card-request-cancel"
						onClick={() => openDialog("cancel")}
					>
						{t("staff.card_request.decision.cancel")}
					</Button>
					<Button
						variant="outline"
						data-testid="card-request-keep"
						onClick={() => openDialog("keep")}
					>
						{t("staff.card_request.decision.keep")}
					</Button>
					<Button
						variant="outline"
						data-testid="card-request-not-cancelled"
						onClick={() => openDialog("not_cancelled_balance")}
					>
						{t("staff.card_request.decision.not_cancelled_balance")}
					</Button>
				</div>
			)}

			<Dialog
				open={decision !== null}
				onOpenChange={(open) => {
					if (!open) {
						closeDialog();
					}
				}}
			>
				<DialogContent data-testid="card-request-dialog">
					<DialogHeader>
						<DialogTitle>{t("staff.card_request.review.title")}</DialogTitle>
						<DialogDescription>
							{decision
								? t(`staff.card_request.decision.${decision}` as TKey)
								: ""}
						</DialogDescription>
					</DialogHeader>
					<div className="flex flex-col gap-1.5">
						<Row
							label={t("staff.card_request.reference")}
							value={request.reference}
						/>
						{decision === "approve" && isCreditOpen && (
							<Row label={t("staff.card_request.credit_limit")} value={limit} />
						)}
						{decision === "decline" && reason && (
							<Row
								label={t("staff.card_request.reason")}
								value={t(`staff.card_request.decline_reason.${reason}` as TKey)}
							/>
						)}
					</div>
					{errorCode && (
						<div
							role="alert"
							className="flex flex-col gap-2 text-sm text-alert"
						>
							<p data-testid="card-request-error">
								{t(`staff.card_request.error.${errorKey}` as TKey)}
							</p>
							{errorCode === "balance_not_zero" && (
								<Button
									variant="outline"
									data-testid="card-request-use-not-cancelled"
									onClick={switchToBalanceDecision}
								>
									{t("staff.card_request.decision.not_cancelled_balance")}
								</Button>
							)}
						</div>
					)}
					<DialogFooter>
						<Button
							variant="outline"
							data-testid="card-request-dialog-back"
							disabled={submitting}
							onClick={closeDialog}
						>
							{t("staff.card_request.review.back")}
						</Button>
						<Button
							data-testid="card-request-dialog-confirm"
							disabled={submitting || confirmBlocked}
							onClick={() => void confirm()}
						>
							{t("staff.card_request.review.confirm")}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</section>
	);
}

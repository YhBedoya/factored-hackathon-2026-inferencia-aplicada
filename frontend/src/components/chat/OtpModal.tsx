import { type FormEvent, useState } from "react";

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
import { ApiError, postResume, verifyOtp } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type OtpModalProps = {
	conversationId: string;
	/** Called once `verifyOtp` succeeds, before `postResume` runs (closes the modal). */
	onVerified: () => void;
};

/**
 * `ui.otp_required` (D2). The code lives only in this component's local
 * state: it never joins the transcript, sessionStorage or a log line (R5,
 * D2). On success it resumes the paused turn with `{resume: "step_up"}`;
 * on `otp_invalid` / `too_many_attempts` it shows the inline error and stays open.
 */
export function OtpModal({ conversationId, onVerified }: OtpModalProps) {
	const { t } = useI18n();
	const [code, setCode] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	async function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setSubmitting(true);
		setError(null);
		try {
			await verifyOtp(code);
			onVerified();
			await postResume(conversationId);
		} catch (err) {
			const errCode = err instanceof ApiError ? err.code : null;
			setError(
				errCode === "otp_invalid"
					? t("errors.otp_invalid")
					: errCode === "too_many_attempts"
						? t("errors.too_many_attempts")
						: t("errors.generic"),
			);
			setSubmitting(false);
		}
	}

	return (
		<Dialog open>
			<DialogContent data-testid="otp-modal">
				<DialogHeader>
					<DialogTitle>{t("otp.title")}</DialogTitle>
					<DialogDescription>{t("otp.description")}</DialogDescription>
				</DialogHeader>
				<form onSubmit={handleSubmit} className="flex flex-col gap-3">
					<Label htmlFor="otp-code">{t("otp.code")}</Label>
					<Input
						id="otp-code"
						data-testid="otp-input"
						value={code}
						onChange={(event) => setCode(event.target.value)}
						autoComplete="one-time-code"
						disabled={submitting}
					/>
					{error && (
						<p data-testid="otp-error" className="text-sm text-alert">
							{error}
						</p>
					)}
					<DialogFooter>
						<Button
							type="submit"
							data-testid="otp-submit"
							disabled={submitting || code.trim().length === 0}
						>
							{t("otp.submit")}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

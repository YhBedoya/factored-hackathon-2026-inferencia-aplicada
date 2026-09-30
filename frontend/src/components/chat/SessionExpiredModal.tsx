import type { MeResponse } from "@/client";
import { LoginForm } from "@/components/auth/LoginForm";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { me, sessionExpired } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type SessionExpiredModalProps = {
	open: boolean;
	/** The session `chat.tsx` captured when the conversation opened (D8); `null` only before that first `me()` resolves. */
	identity: MeResponse | null;
	/** Fires once the held request has been replayed, after a same-customer re-login. */
	onResume: () => void;
	/** Fires on a different-customer re-login: the held request was dropped. */
	onMismatch: () => void;
};

function sameCustomer(a: MeResponse, b: MeResponse): boolean {
	return a.login_hint === b.login_hint && a.display_name === b.display_name;
}

/**
 * D8/B2: what a `401 session_expired` shows the customer instead of the old
 * hard redirect. `withAuthRetry` (`lib/api.ts`) holds the failed request in
 * `sessionExpired`; this modal is the only place that resolves it. It
 * re-checks who is logged in with a fresh `GET /auth/me` rather than trusting
 * the login response, the same check the scripted/simulator drivers make
 * (R1/R13: there is no `customer_id` here to compare, only what the session
 * cookie proves). A match replays the held request once and hands back to
 * `chat.tsx` to reopen the stream; anything else drops it and starts a fresh
 * conversation.
 */
export function SessionExpiredModal({
	open,
	identity,
	onResume,
	onMismatch,
}: SessionExpiredModalProps) {
	const { t } = useI18n();

	async function handleLoginSuccess() {
		const current = await me();
		if (identity && current && sameCustomer(identity, current)) {
			await sessionExpired.replay();
			onResume();
		} else {
			sessionExpired.drop();
			onMismatch();
		}
	}

	return (
		<Dialog open={open}>
			<DialogContent
				data-testid="session-expired-modal"
				showCloseButton={false}
				onEscapeKeyDown={(event) => event.preventDefault()}
				onInteractOutside={(event) => event.preventDefault()}
			>
				<DialogHeader>
					<DialogTitle>{t("session_expired.title")}</DialogTitle>
					<DialogDescription>
						{t("session_expired.description")}
					</DialogDescription>
				</DialogHeader>
				<LoginForm onSuccess={handleLoginSuccess} />
			</DialogContent>
		</Dialog>
	);
}

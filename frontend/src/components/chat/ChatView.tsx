import { useQueryClient } from "@tanstack/react-query";
import {
	type ReactNode,
	useCallback,
	useEffect,
	useRef,
	useState,
} from "react";

import type { MeResponse, ProfileFormView } from "@/client";
import { Composer } from "@/components/chat/Composer";
import {
	MessageList,
	type TranscriptMessage,
} from "@/components/chat/MessageList";
import { ModeIndicator } from "@/components/chat/ModeIndicator";
import { OtpModal } from "@/components/chat/OtpModal";
import { ProfileForm } from "@/components/chat/ProfileForm";
import { SessionExpiredModal } from "@/components/chat/SessionExpiredModal";
import { CARDS_KEY } from "@/components/home/queries";
import { Button } from "@/components/ui/button";
import {
	ApiError,
	type ConfirmationDecision,
	conversationStore,
	createConversation,
	getProfileForm,
	me,
	postCardSelection,
	postConfirmation,
	postMessage,
	postSelection,
	postStepUpCancel,
	sessionExpired,
} from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import { type ModePayload, openConversationStream } from "@/lib/sse";
import { newId } from "@/lib/uuid";

// Every error/otp code this card knows a dictionary string for. Anything
// else falls back to `errors.generic` rather than showing a raw code (R4
// spirit: no server string reaches the customer unformatted).
const KNOWN_ERROR_CODES = new Set([
	"invalid_credentials",
	"too_many_attempts",
	"turn_failed",
	"turn_in_progress",
	"conversation_closed",
	"otp_invalid",
	"confirmation_invalid",
	"selection_required",
	"form_required",
]);

// D12: 429 and 5xx are mapped by HTTP status, ahead of the `code` (detail)
// lookup -- a 5xx body isn't guaranteed to carry a JSON `detail` at all (a
// gateway error, for one), so the status is the only reliable signal.
function errorKey(code: string, status: number | null): TKey {
	if (status === 429) {
		return "errors.rate_limited";
	}
	if (status !== null && status >= 500) {
		return "errors.server_error";
	}
	return (
		KNOWN_ERROR_CODES.has(code) ? `errors.${code}` : "errors.generic"
	) as TKey;
}

type ChatViewProps = {
	/** Text dropped into the composer (never auto-sent), e.g. from a home shortcut. */
	prefill?: string;
	/** Sizing for the host; defaults to the full-page `h-dvh` column. */
	className?: string;
	/**
	 * Ignore the stored conversation and open a new one with Cardy's welcome.
	 * The home panel unmounts on close, so each open is a fresh conversation.
	 */
	fresh?: boolean;
	/** A control shown at the right of the name row, e.g. the home panel's close button. */
	headerAction?: ReactNode;
	/** Called on each Cardy or agent reply, e.g. to flag a minimized panel. */
	onReply?: () => void;
};

export function ChatView({
	prefill,
	className = "h-dvh",
	fresh = false,
	headerAction,
	onReply,
}: ChatViewProps) {
	const { t, lang } = useI18n();
	const queryClient = useQueryClient();
	const conversationIdRef = useRef<string | null>(
		fresh ? null : conversationStore.get(),
	);
	const streamCleanupRef = useRef<(() => void) | null>(null);
	const pendingUiRef = useRef<TranscriptMessage["ui"]>([]);
	// `connectStream` is created once, so it reads the latest callback here.
	const onReplyRef = useRef(onReply);
	onReplyRef.current = onReply;

	const [conversationId, setConversationId] = useState(
		conversationIdRef.current,
	);
	const [messages, setMessages] = useState<TranscriptMessage[]>([]);
	const [typing, setTyping] = useState(false);
	const [reconnecting, setReconnecting] = useState(false);
	const [composerDisabled, setComposerDisabled] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const [errorStatus, setErrorStatus] = useState<number | null>(null);
	const [closed, setClosed] = useState(false);
	const [otpTool, setOtpTool] = useState<string | null>(null);
	// The open profile form (`ui.profile_form`, D11): only the card kind lives
	// here. The form's values stay in `ProfileForm`'s own state (R5).
	// Set by the mount probe, so the form does not fetch its view twice.
	const [formView, setFormView] = useState<ProfileFormView | null>(null);
	const lastFormKindRef = useRef<"credit" | "debit">("credit");
	const [formKind, setFormKind] = useState<"credit" | "debit" | null>(null);
	const [mode, setMode] = useState<ModePayload>({
		mode: "bot",
		agent_display_name: null,
	});
	// The multi-card picker is open until its message is answered (D39): the
	// last `card_picker` is `multi` and not the one the customer submitted.
	const [usedPickerId, setUsedPickerId] = useState<string | null>(null);
	const [sessionExpiredOpen, setSessionExpiredOpen] = useState(false);
	// D8: captured once, on mount, so a later re-login is checked against who
	// the chat started as, not against a display name that could since change.
	const [identity, setIdentity] = useState<MeResponse | null>(null);

	const lastPickerMessage = [...messages]
		.reverse()
		.find((m) => m.ui.some((e) => e.kind === "card_picker"));
	const pickerOpen =
		!!lastPickerMessage &&
		lastPickerMessage.id !== usedPickerId &&
		lastPickerMessage.ui.some(
			(e) => e.kind === "card_picker" && e.payload.multi === true,
		);

	const connectStream = useCallback(
		(id: string) => {
			streamCleanupRef.current?.();
			streamCleanupRef.current = openConversationStream(id, {
				onStatus: () => setTyping(true),
				onMessage: (payload) => {
					setTyping(false);
					// In human mode the server relays the customer's own text back
					// for the agent (`04` §3); it is already in the list.
					if (payload.role === "customer") {
						return;
					}
					onReplyRef.current?.();
					if (payload.role !== "bot") {
						// An agent reply, or the fixed system line on return to bot.
						setMessages((prev) => [
							...prev,
							{
								id: newId(),
								role: payload.role,
								text: payload.text,
								author: payload.agent_display_name ?? null,
								ui: [],
							},
						]);
						return;
					}
					const ui = pendingUiRef.current;
					pendingUiRef.current = [];
					setMessages((prev) => [
						...prev,
						{ id: newId(), role: "bot", text: payload.text, ui },
					]);
				},
				onUi: (event) => {
					pendingUiRef.current = [...pendingUiRef.current, event];
					if (event.kind === "otp_required") {
						setOtpTool(event.payload.tool);
					} else if (event.kind === "profile_form") {
						lastFormKindRef.current = event.payload.card_kind;
						setFormKind(event.payload.card_kind);
					} else if (event.kind === "conversation_closed") {
						setClosed(true);
					}
				},
				onMode: (payload) => setMode(payload),
				// `cards_changed` (D9-C AS10): the home card list and every card detail are stale.
				onCardsChanged: () => {
					queryClient.invalidateQueries({ queryKey: CARDS_KEY });
					queryClient.invalidateQueries({ queryKey: ["home", "card"] });
				},
				onError: (payload) => {
					setTyping(false);
					// SSE `error {code}` carries no HTTP status (`04` §3); only
					// `turn_failed` reaches here today, already in `KNOWN_ERROR_CODES`.
					setErrorCode(payload.code);
					setErrorStatus(null);
				},
				onDone: () => {
					setTyping(false);
					setComposerDisabled(false);
				},
				onReconnecting: () => setReconnecting(true),
				onOpen: () => setReconnecting(false),
			});
		},
		[queryClient],
	);

	const declinedOnMountRef = useRef(false);
	const createRef = useRef<Promise<string> | null>(null);

	// D2: one create (with the welcome) per empty conversation. The promise is
	// kept in a ref so StrictMode's double mount, a fast click and the lazy
	// `ensureConversation` below all reuse the same in-flight call.
	const startConversation = useCallback(
		(withWelcome: boolean): Promise<string> => {
			if (createRef.current) {
				return createRef.current;
			}
			const pendingCreate = createConversation(lang, {
				welcome: withWelcome,
			})
				.then(({ conversationId: id, welcome }) => {
					conversationStore.set(id);
					conversationIdRef.current = id;
					setConversationId(id);
					// D12: the stream opens before the first `postMessage`.
					connectStream(id);
					if (welcome) {
						setMessages((prev) => [
							...prev,
							{ id: newId(), role: "bot", text: welcome, ui: [] },
						]);
					}
					return id;
				})
				.finally(() => {
					createRef.current = null;
				});
			createRef.current = pendingCreate;
			return pendingCreate;
		},
		[lang, connectStream],
	);

	// A reload keeps the stored conversation id (no history route, D12), so it
	// only re-opens the stream: no create, no welcome (D2). A `fresh` host
	// never reuses it, so it always starts with the welcome.
	// biome-ignore lint/correctness/useExhaustiveDependencies: mount-only; a `lang` change must not re-create.
	useEffect(() => {
		if (conversationIdRef.current) {
			connectStream(conversationIdRef.current);
			// A reload loses an open multi picker, so the pending offer is
			// declined once (D39); 409/429 mean there was nothing to decline.
			if (!declinedOnMountRef.current) {
				declinedOnMountRef.current = true;
				const mountId = conversationIdRef.current;
				// D16: a reload loses an open agent OTP modal, so the pause is
				// cancelled once. Chained after the picker decline so the two
				// posts never race for the same turn; any 409 is ignored.
				// D11: a reload keeps a pending profile-form pause, so it is
				// re-opened. The GET answers only while the pause is pending
				// (`409 form_not_open` otherwise, ignored): nothing to restore.
				getProfileForm(mountId)
					.then((view) => {
						lastFormKindRef.current = view.card_kind ?? "credit";
						setFormView(view);
						setFormKind(view.card_kind ?? "credit");
					})
					.catch(() => {});
				postCardSelection(mountId, [])
					.catch(() => {})
					.then(() => postStepUpCancel(mountId))
					.catch(() => {});
			}
		} else {
			startConversation(true).catch(() => {
				// The lazy `ensureConversation` retries on the first send.
			});
		}
		return () => streamCleanupRef.current?.();
	}, []);

	useEffect(() => {
		me().then(setIdentity);
	}, []);

	// D8: the chat is the only caller that holds a `401 session_expired`
	// instead of letting `withAuthRetry` redirect to the login pop-up.
	useEffect(() => {
		sessionExpired.register(() => setSessionExpiredOpen(true));
		return () => sessionExpired.unregister();
	}, []);

	async function ensureConversation(): Promise<string> {
		if (conversationIdRef.current) {
			return conversationIdRef.current;
		}
		return startConversation(false);
	}

	function clearError() {
		setErrorCode(null);
		setErrorStatus(null);
	}

	function handleTurnError(err: unknown, typedBubbleId?: string) {
		if (
			err instanceof ApiError &&
			err.status === 409 &&
			err.code === "selection_required"
		) {
			// A typed answer at the picker is refused: drop the bubble. A page
			// with no picker of its own (second tab) declines the offer.
			if (typedBubbleId) {
				setMessages((prev) => prev.filter((m) => m.id !== typedBubbleId));
			}
			setComposerDisabled(false);
			if (!pickerOpen && conversationIdRef.current) {
				postCardSelection(conversationIdRef.current, []).catch(() => {});
			}
			setErrorCode("selection_required");
			setErrorStatus(409);
			return;
		}
		if (
			err instanceof ApiError &&
			err.status === 409 &&
			err.code === "otp_required"
		) {
			// Typed text at the agent OTP pause is refused (D15): drop the
			// bubble and re-open the modal, which keeps the input disabled.
			if (typedBubbleId) {
				setMessages((prev) => prev.filter((m) => m.id !== typedBubbleId));
			}
			setOtpTool((prev) => prev ?? "agent");
			return;
		}
		if (
			err instanceof ApiError &&
			err.status === 409 &&
			err.code === "form_required"
		) {
			// Typed text at the form pause is refused (D11): drop the bubble and
			// re-open the form (a reload lost it); the pause itself is kept.
			if (typedBubbleId) {
				setMessages((prev) => prev.filter((m) => m.id !== typedBubbleId));
			}
			setComposerDisabled(false);
			// Fallback re-open: the form's own GET sets the title kind; until it
			// answers, use the last kind seen.
			setFormKind((prev) => prev ?? lastFormKindRef.current);
			setErrorCode("form_required");
			setErrorStatus(409);
			return;
		}
		if (err instanceof ApiError && err.code === "session_replay_dropped") {
			// D8: `SessionExpiredModal`'s mismatch branch already reset the chat.
			return;
		}
		if (
			err instanceof ApiError &&
			err.status === 409 &&
			err.code === "conversation_closed"
		) {
			setClosed(true);
			return;
		}
		setErrorCode(err instanceof ApiError ? err.code : "generic");
		setErrorStatus(err instanceof ApiError ? err.status : null);
		setComposerDisabled(false);
	}

	async function handleSend(text: string) {
		const bubbleId = newId();
		setMessages((prev) => [
			...prev,
			{ id: bubbleId, role: "customer", text, ui: [] },
		]);
		setComposerDisabled(true);
		clearError();
		try {
			const id = await ensureConversation();
			await postMessage(id, text);
		} catch (err) {
			handleTurnError(err, bubbleId);
		}
	}

	async function handleConfirmDecision(
		tokenId: string,
		decision: ConfirmationDecision,
	) {
		clearError();
		try {
			const id = await ensureConversation();
			setComposerDisabled(true);
			await postConfirmation(id, tokenId, decision);
		} catch (err) {
			handleTurnError(err);
		}
	}

	// D7: the pick is never shown as a customer bubble, only posted.
	async function handleTransactionSelect(txIds: string[]) {
		clearError();
		try {
			const id = await ensureConversation();
			setComposerDisabled(true);
			await postSelection(id, txIds);
		} catch (err) {
			handleTurnError(err);
		}
	}

	// Like the transaction pick: never a customer bubble. An empty list is the
	// "No, gracias" decline. A failed post reopens the picker.
	async function handleCardSelect(cardIds: string[]) {
		clearError();
		const pickerId = lastPickerMessage?.id ?? null;
		setUsedPickerId(pickerId);
		try {
			const id = await ensureConversation();
			setComposerDisabled(true);
			await postCardSelection(id, cardIds);
		} catch (err) {
			setUsedPickerId(null);
			handleTurnError(err);
		}
	}

	function handleOtpVerified() {
		setOtpTool(null);
		setComposerDisabled(true);
	}

	// `429 otp_handoff`: close the modal; the handoff reply, banner and mode
	// event arrive on the stream, so the composer stays off until they do.
	function handleOtpHandoff() {
		setOtpTool(null);
		setComposerDisabled(true);
	}

	async function handleOtpCancel() {
		clearError();
		setOtpTool(null);
		try {
			const id = await ensureConversation();
			setComposerDisabled(true);
			await postStepUpCancel(id);
		} catch (err) {
			// No pause open (or already resolved): nothing to cancel.
			if (err instanceof ApiError && err.code === "cancel_invalid") {
				setComposerDisabled(false);
				return;
			}
			handleTurnError(err);
		}
	}

	// Send and Cancel both close the form; the resumed turn's events follow on
	// the stream, so the composer stays off until `done`.
	function handleFormClosed() {
		setFormKind(null);
		setFormView(null);
		setComposerDisabled(true);
	}

	function handleNewConversation() {
		streamCleanupRef.current?.();
		streamCleanupRef.current = null;
		conversationStore.clear();
		conversationIdRef.current = null;
		pendingUiRef.current = [];
		setConversationId(null);
		setMessages([]);
		setClosed(false);
		clearError();
		setComposerDisabled(false);
		setTyping(false);
		setOtpTool(null);
		setFormKind(null);
		setFormView(null);
		setMode({ mode: "bot", agent_display_name: null });
		startConversation(true).catch(() => {
			// The lazy `ensureConversation` retries on the first send.
		});
	}

	// D8: a same-customer re-login just resumes the stream; the replay itself
	// already went through `sessionExpired.replay()` before this runs.
	function handleSessionResume() {
		setSessionExpiredOpen(false);
		if (conversationIdRef.current) {
			connectStream(conversationIdRef.current);
		}
	}

	function handleSessionMismatch() {
		setSessionExpiredOpen(false);
		handleNewConversation();
	}

	return (
		// `chat-shell` scopes the mobile touch-target and overflow rules in
		// `index.css` (D13) to this page, without touching the shared
		// `ui/button`/`ui/input` primitives or the picker/confirm/list widgets.
		<div
			className={`chat-shell flex flex-col overflow-x-hidden bg-bg ${className}`}
		>
			<div className="flex items-center justify-between">
				<ModeIndicator
					mode={mode.mode}
					agentDisplayName={mode.agent_display_name}
				/>
				{headerAction && <div className="px-4">{headerAction}</div>}
			</div>
			<MessageList
				messages={messages}
				typing={typing}
				onWidgetSelect={handleSend}
				onConfirmDecision={handleConfirmDecision}
				onTransactionSelect={handleTransactionSelect}
				onCardSelect={handleCardSelect}
			/>
			{reconnecting && (
				<div
					data-testid="reconnecting"
					className="px-4 py-1 text-sm text-muted-foreground"
				>
					{t("chat.reconnecting")}
				</div>
			)}
			{errorCode && (
				<div role="alert" className="px-4 py-1 text-sm text-alert">
					{t(errorKey(errorCode, errorStatus))}
				</div>
			)}
			{closed && (
				<div className="flex items-center justify-between gap-2 px-4 py-2">
					<p className="text-sm text-muted-foreground">
						{t("chat.closed_notice")}
					</p>
					<Button
						data-testid="new-conversation"
						onClick={handleNewConversation}
					>
						{t("chat.new_conversation")}
					</Button>
				</div>
			)}
			{otpTool && conversationId && (
				<OtpModal
					conversationId={conversationId}
					onVerified={handleOtpVerified}
					onCancel={handleOtpCancel}
					onHandoff={handleOtpHandoff}
				/>
			)}
			{formKind && conversationId && (
				<ProfileForm
					conversationId={conversationId}
					cardKind={formKind}
					initialView={formView ?? undefined}
					onClosed={handleFormClosed}
				/>
			)}
			<SessionExpiredModal
				open={sessionExpiredOpen}
				identity={identity}
				onResume={handleSessionResume}
				onMismatch={handleSessionMismatch}
			/>
			<Composer
				disabled={
					composerDisabled || closed || pickerOpen || !!otpTool || !!formKind
				}
				onSend={handleSend}
				prefill={prefill}
			/>
		</div>
	);
}

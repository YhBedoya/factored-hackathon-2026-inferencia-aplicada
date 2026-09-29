import { createFileRoute, redirect } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { Composer } from "@/components/chat/Composer";
import {
	MessageList,
	type TranscriptMessage,
} from "@/components/chat/MessageList";
import { ModeIndicator } from "@/components/chat/ModeIndicator";
import { OtpModal } from "@/components/chat/OtpModal";
import { Button } from "@/components/ui/button";
import {
	ApiError,
	type ConfirmationDecision,
	conversationStore,
	createConversation,
	me,
	postConfirmation,
	postMessage,
	postSelection,
} from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";
import { type ModePayload, openConversationStream } from "@/lib/sse";

// R1/D3-B D12: the chat guard is the one place `me()` decides who reaches the
// conversation. Nothing here ever sends a `customer_id`; the session cookie
// carries it, and every request below rides on that same cookie.
export const Route = createFileRoute("/chat")({
	beforeLoad: async () => {
		const customer = await me();
		if (!customer) {
			throw redirect({ to: "/login" });
		}
	},
	component: ChatPage,
});

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
]);

function errorKey(code: string): TKey {
	return (
		KNOWN_ERROR_CODES.has(code) ? `errors.${code}` : "errors.generic"
	) as TKey;
}

function ChatPage() {
	const { t, lang } = useI18n();
	const conversationIdRef = useRef<string | null>(conversationStore.get());
	const streamCleanupRef = useRef<(() => void) | null>(null);
	const pendingUiRef = useRef<TranscriptMessage["ui"]>([]);

	const [conversationId, setConversationId] = useState(
		conversationIdRef.current,
	);
	const [messages, setMessages] = useState<TranscriptMessage[]>([]);
	const [typing, setTyping] = useState(false);
	const [reconnecting, setReconnecting] = useState(false);
	const [composerDisabled, setComposerDisabled] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);
	const [closed, setClosed] = useState(false);
	const [otpTool, setOtpTool] = useState<string | null>(null);
	const [mode, setMode] = useState<ModePayload>({
		mode: "bot",
		agent_display_name: null,
	});

	const connectStream = useCallback((id: string) => {
		streamCleanupRef.current?.();
		streamCleanupRef.current = openConversationStream(id, {
			onStatus: () => setTyping(true),
			onMessage: (payload) => {
				setTyping(false);
				if (payload.role !== "bot") {
					return;
				}
				const ui = pendingUiRef.current;
				pendingUiRef.current = [];
				setMessages((prev) => [
					...prev,
					{ id: crypto.randomUUID(), role: "bot", text: payload.text, ui },
				]);
			},
			onUi: (event) => {
				pendingUiRef.current = [...pendingUiRef.current, event];
				if (event.kind === "otp_required") {
					setOtpTool(event.payload.tool);
				} else if (event.kind === "conversation_closed") {
					setClosed(true);
				}
			},
			onMode: (payload) => setMode(payload),
			onError: (payload) => {
				setTyping(false);
				setErrorCode(payload.code);
			},
			onDone: () => {
				setTyping(false);
				setComposerDisabled(false);
			},
			onReconnecting: () => setReconnecting(true),
			onOpen: () => setReconnecting(false),
		});
	}, []);

	// A reload keeps the stored conversation id (no history route, D12), so
	// re-open the stream for it. A brand-new conversation is opened lazily by
	// `ensureConversation` on the first send instead.
	useEffect(() => {
		if (conversationIdRef.current) {
			connectStream(conversationIdRef.current);
		}
		return () => streamCleanupRef.current?.();
	}, [connectStream]);

	async function ensureConversation(): Promise<string> {
		if (conversationIdRef.current) {
			return conversationIdRef.current;
		}
		const id = await createConversation(lang);
		conversationStore.set(id);
		conversationIdRef.current = id;
		setConversationId(id);
		// D12: the stream opens before the first `postMessage`.
		connectStream(id);
		return id;
	}

	function handleTurnError(err: unknown) {
		if (
			err instanceof ApiError &&
			err.status === 409 &&
			err.code === "conversation_closed"
		) {
			setClosed(true);
			return;
		}
		setErrorCode(err instanceof ApiError ? err.code : "generic");
		setComposerDisabled(false);
	}

	async function handleSend(text: string) {
		setMessages((prev) => [
			...prev,
			{ id: crypto.randomUUID(), role: "customer", text, ui: [] },
		]);
		setComposerDisabled(true);
		setErrorCode(null);
		try {
			const id = await ensureConversation();
			await postMessage(id, text);
		} catch (err) {
			handleTurnError(err);
		}
	}

	async function handleConfirmDecision(
		tokenId: string,
		decision: ConfirmationDecision,
	) {
		setErrorCode(null);
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
		setErrorCode(null);
		try {
			const id = await ensureConversation();
			setComposerDisabled(true);
			await postSelection(id, txIds);
		} catch (err) {
			handleTurnError(err);
		}
	}

	function handleOtpVerified() {
		setOtpTool(null);
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
		setErrorCode(null);
		setComposerDisabled(false);
		setTyping(false);
		setOtpTool(null);
		setMode({ mode: "bot", agent_display_name: null });
	}

	return (
		<div className="flex h-dvh flex-col bg-bg">
			<ModeIndicator
				mode={mode.mode}
				agentDisplayName={mode.agent_display_name}
			/>
			<MessageList
				messages={messages}
				typing={typing}
				onWidgetSelect={handleSend}
				onConfirmDecision={handleConfirmDecision}
				onTransactionSelect={handleTransactionSelect}
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
					{t(errorKey(errorCode))}
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
				/>
			)}
			<Composer disabled={composerDisabled || closed} onSend={handleSend} />
		</div>
	);
}

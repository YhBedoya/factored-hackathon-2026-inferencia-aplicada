// Typed wrapper over the native `EventSource` for `GET /conversations/{id}/stream`
// (D12, `04` §3 "SSE events"). It is a thin listener registry: `EventSource`
// itself owns the connection, the retry backoff and the reconnect, so there
// is nothing to replay here (R11 doesn't apply to a read-only stream).

/** One clickable option, code-formatted server-side (R4). */
export type PickerOption = { label: string };

export type CardPickerPayload = { options: PickerOption[] };
export type CardPickerUiEvent = {
	kind: "card_picker";
	payload: CardPickerPayload;
};

export type QuickRepliesPayload = {
	slot: "block_kind";
	options: PickerOption[];
};
export type QuickRepliesUiEvent = {
	kind: "quick_replies";
	payload: QuickRepliesPayload;
};

/** One confirmation-plan step, exactly as `ui.py`'s `ConfirmStepView` sends it. */
export type ConfirmStepView = {
	tool: string;
	summary_key: string;
	facts: { key: string; value: string | number | null; source: string }[];
};
export type ConfirmPayload = { token_id: string; steps: ConfirmStepView[] };
export type ConfirmUiEvent = { kind: "confirm"; payload: ConfirmPayload };

export type OtpRequiredPayload = { tool: string };
export type OtpRequiredUiEvent = {
	kind: "otp_required";
	payload: OtpRequiredPayload;
};

export type ConversationClosedUiEvent = {
	kind: "conversation_closed";
	payload: Record<string, never>;
};

/** The five `ui` kinds this card renders (`transaction_list`/`handoff_banner` aren't defined yet). */
export type UiEvent =
	| CardPickerUiEvent
	| QuickRepliesUiEvent
	| ConfirmUiEvent
	| OtpRequiredUiEvent
	| ConversationClosedUiEvent;

export type StatusPayload = { step: string };
export type MessagePayload = {
	role: "bot" | "customer" | "agent";
	text: string;
	sources: string[];
};
export type ErrorPayload = { code: string };
export type DonePayload = { turn_id: string };

export type ConversationStreamHandlers = {
	onStatus: (payload: StatusPayload) => void;
	onMessage: (payload: MessagePayload) => void;
	onUi: (event: UiEvent) => void;
	onError: (payload: ErrorPayload) => void;
	onDone: (payload: DonePayload) => void;
	/** Fires on every drop; `EventSource` reconnects on its own, no replay. */
	onReconnecting: () => void;
	/** Fires once the (re)connection is live, clearing the banner. */
	onOpen: () => void;
};

function parse<T>(event: Event): T {
	return JSON.parse((event as globalThis.MessageEvent).data) as T;
}

/**
 * Opens the stream and wires the five event names this card renders. `debug`
 * and `mode` are intentionally left unhandled: they arrive under their own
 * SSE `event:` name, so the default `message` listener never sees them, and
 * they are simply never delivered anywhere (D12).
 *
 * Returns a cleanup function that closes the connection.
 */
export function openConversationStream(
	conversationId: string,
	handlers: ConversationStreamHandlers,
): () => void {
	const source = new EventSource(
		`/api/v1/conversations/${conversationId}/stream`,
	);

	source.addEventListener("status", (event) => {
		handlers.onStatus(parse<StatusPayload>(event));
	});
	source.addEventListener("message", (event) => {
		handlers.onMessage(parse<MessagePayload>(event));
	});
	source.addEventListener("ui", (event) => {
		handlers.onUi(parse<UiEvent>(event));
	});
	// `error` is a reserved `EventSource` type: a dropped connection dispatches
	// a plain `Event` here, and the server's named `event: error` frame also
	// dispatches *here* (the SSE event name becomes the DOM event type), as a
	// `MessageEvent` with `.data`. `onerror`/`addEventListener` would both fire
	// on every one of these, so there is exactly one listener that branches on
	// the event class instead of two competing handlers (D12, R11 n/a: this is
	// a read-only stream `EventSource` itself retries).
	source.addEventListener("error", (event) => {
		if (event instanceof globalThis.MessageEvent) {
			handlers.onError(parse<ErrorPayload>(event));
		} else {
			handlers.onReconnecting();
		}
	});
	source.addEventListener("done", (event) => {
		handlers.onDone(parse<DonePayload>(event));
	});

	source.onopen = () => handlers.onOpen();

	return () => source.close();
}

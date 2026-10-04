import {
	type AnalyticsSummary,
	type CardDetailsView,
	type CardView,
	type ConversationPage,
	type ConversationTimeline,
	claimHandoffApiV1StaffHandoffsHandoffIdClaimPost,
	createConversationApiV1ConversationsPost,
	type GetAnalyticsSummaryApiV1StaffAnalyticsSummaryGetData,
	getAnalyticsSummaryApiV1StaffAnalyticsSummaryGet,
	getCardApiV1MeCardsCardIdGet,
	getConversationTimelineApiV1StaffConversationsConversationIdTimelineGet,
	getHandoffApiV1StaffHandoffsHandoffIdGet,
	type HandoffDetail,
	type HandoffSummary,
	type ListConversationsApiV1StaffConversationsGetData,
	type LoginRequest,
	listCardsApiV1MeCardsGet,
	listConversationMessagesApiV1StaffConversationsConversationIdMessagesGet,
	listConversationsApiV1StaffConversationsGet,
	listHandoffsApiV1StaffHandoffsGet,
	listTransactionsApiV1MeTransactionsGet,
	loginApiV1AuthLoginPost,
	logoutApiV1AuthLogoutPost,
	type MeResponse,
	meApiV1AuthMeGet,
	postConversationMessageApiV1StaffConversationsConversationIdMessagesPost,
	postMessageApiV1ConversationsConversationIdMessagesPost,
	type Rate,
	type RecentInteraction,
	refreshApiV1AuthRefreshPost,
	returnHandoffApiV1StaffHandoffsHandoffIdReturnPost,
	type StaffLoginRequest,
	type StaffMeResponse,
	staffLoginApiV1AuthStaffLoginPost,
	staffLogoutApiV1StaffLogoutPost,
	staffMeApiV1StaffMeGet,
	type TranscriptMessage,
	type TxPage,
} from "@/client";
import { client } from "@/client/client.gen";
import type { Lang } from "@/lib/i18n";

const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";

function readCookie(name: string): string | null {
	const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
	return match ? decodeURIComponent(match[1]) : null;
}

// R1/D11: the session cookie carries `customer_id`; nothing here ever sends
// one. The only thing this interceptor adds is the CSRF double-submit
// header, and only on requests that can have a side effect.
client.interceptors.request.use((request) => {
	if (request.method !== "GET") {
		const token = readCookie(CSRF_COOKIE);
		if (token) {
			request.headers.set(CSRF_HEADER, token);
		}
	}
	return request;
});

/** Typed API error. `code` is the FastAPI `detail` string (`04` error shapes). */
export class ApiError extends Error {
	status: number;
	code: string;

	constructor(status: number, code: string) {
		super(code);
		this.status = status;
		this.code = code;
	}
}

function errorCode(error: unknown): string {
	if (
		error &&
		typeof error === "object" &&
		"detail" in error &&
		typeof (error as { detail: unknown }).detail === "string"
	) {
		return (error as { detail: string }).detail;
	}
	return "generic";
}

// `response` is optional on the generated result type: it is missing only
// when the request never made it to the network (D11 doesn't cover that
// case, so it is treated as a plain, non-retryable error below).
type FetchResult<T> = { data?: T; error?: unknown; response?: Response };

function statusOf(result: FetchResult<unknown>): number {
	return result.response?.status ?? 0;
}

function unwrap<T>(result: FetchResult<T>): T {
	if (result.error !== undefined || !result.response?.ok) {
		throw new ApiError(statusOf(result), errorCode(result.error));
	}
	return result.data as T;
}

// D8/D11: a 401 on anything but login/refresh gets one refresh-and-retry.
// When that still fails, the chat (if mounted) holds the request instead of
// redirecting -- see `sessionExpired` below. Every other route has nothing
// registered, so it keeps the old redirect. `login` and `refresh` never call
// this (they are the exempt paths).
async function withAuthRetry<T>(
	exec: () => Promise<FetchResult<T>>,
): Promise<FetchResult<T>> {
	const first = await exec();
	if (statusOf(first) !== 401) {
		return first;
	}
	const refresh = await refreshApiV1AuthRefreshPost();
	if (!refresh.response?.ok) {
		return sessionExpired.hold(exec) ?? redirectToLogin(first);
	}
	const second = await exec();
	if (statusOf(second) === 401) {
		return sessionExpired.hold(exec) ?? redirectToLogin(second);
	}
	return second;
}

function redirectToLogin<T>(result: FetchResult<T>): FetchResult<T> {
	window.location.assign("/?login=1");
	return result;
}

type Replay<T> = () => Promise<FetchResult<T>>;

type PendingExpiry = {
	replay: Replay<unknown>;
	resolve: (result: FetchResult<unknown>) => void;
	reject: (error: unknown) => void;
};

// D8: the chat is the only caller that ever holds a session-expired request.
// It registers a listener on mount (opens the modal) and unregisters on
// unmount, so `hold` below falls back to the redirect everywhere else. Only
// one request is ever held at a time, matching R11's bounded-retry spirit --
// there is exactly one replay, never a queue of them.
let expiredListener: (() => void) | null = null;
let pending: PendingExpiry | null = null;

export const sessionExpired = {
	register(listener: () => void): void {
		expiredListener = listener;
	},
	unregister(): void {
		expiredListener = null;
		pending = null;
	},
	/**
	 * Called by `withAuthRetry` in place of the redirect. Returns `null` when
	 * nothing is registered, so the caller falls back to `redirectToLogin`.
	 */
	hold<T>(retry: Replay<T>): Promise<FetchResult<T>> | null {
		if (!expiredListener) {
			return null;
		}
		const notify = expiredListener;
		return new Promise<FetchResult<T>>((resolve, reject) => {
			pending = {
				replay: retry as Replay<unknown>,
				resolve: resolve as (result: FetchResult<unknown>) => void,
				reject,
			};
			notify();
		});
	},
	/** `SessionExpiredModal` calls this after a same-customer re-login (D8). */
	async replay(): Promise<void> {
		const held = pending;
		pending = null;
		if (!held) {
			return;
		}
		try {
			held.resolve(await held.replay());
		} catch (error) {
			held.reject(error);
		}
	},
	/**
	 * `SessionExpiredModal` calls this on a different-customer re-login (D8):
	 * the held request is dropped, so its caller's `await` rejects and never
	 * retries -- `chat.tsx` recognizes this code and starts a fresh
	 * conversation instead of showing it as a turn error.
	 */
	drop(): void {
		const held = pending;
		pending = null;
		held?.reject(new ApiError(0, "session_replay_dropped"));
	},
};

export async function login(body: LoginRequest): Promise<MeResponse> {
	const result = await loginApiV1AuthLoginPost({ body });
	return unwrap(result);
}

export async function logout(): Promise<void> {
	const result = await withAuthRetry(() => logoutApiV1AuthLogoutPost());
	unwrap(result);
}

// `null` on 401, with no redirect (T3/T4 use this for the shell/chat guard,
// which decide for themselves what "not logged in" means).
export async function me(): Promise<MeResponse | null> {
	const result = await meApiV1AuthMeGet();
	if (statusOf(result) === 401) {
		return null;
	}
	return unwrap(result);
}

export async function createConversation(
	lang: Lang,
	opts?: { welcome?: boolean },
): Promise<{ conversationId: string; welcome: string | null }> {
	const result = await withAuthRetry(() =>
		createConversationApiV1ConversationsPost({
			body: { language: lang, welcome: opts?.welcome ?? false },
		}),
	);
	const data = unwrap(result);
	return {
		conversationId: data.conversation_id,
		welcome: data.welcome?.text ?? null,
	};
}

// D6/D7: the banking home's read-only views. Display strings (money, dates,
// masks) come from the server; nothing here ever sends a `customer_id`.
export async function listMyCards(): Promise<CardView[]> {
	const result = await withAuthRetry(() => listCardsApiV1MeCardsGet());
	return unwrap(result);
}

export async function getMyCard(cardId: string): Promise<CardDetailsView> {
	const result = await withAuthRetry(() =>
		getCardApiV1MeCardsCardIdGet({ path: { card_id: cardId } }),
	);
	return unwrap(result);
}

export async function listMyTransactions(opts?: {
	cardId?: string;
	dateFrom?: string;
	dateTo?: string;
	cursor?: string;
}): Promise<TxPage> {
	const result = await withAuthRetry(() =>
		listTransactionsApiV1MeTransactionsGet({
			query: {
				card_id: opts?.cardId || undefined,
				date_from: opts?.dateFrom || undefined,
				date_to: opts?.dateTo || undefined,
				cursor: opts?.cursor || undefined,
			},
		}),
	);
	return unwrap(result);
}

export async function postMessage(
	conversationId: string,
	text: string,
): Promise<string> {
	const result = await withAuthRetry(() =>
		postMessageApiV1ConversationsConversationIdMessagesPost({
			path: { conversation_id: conversationId },
			body: { text },
		}),
	);
	return unwrap(result).turn_id;
}

// D4-B D7: the pick step's input. `TxSelection` is never persisted as a
// customer message (the route/flow re-check the ids against
// `dispute.offered_tx_ids`), so this posts through the same generated
// `PostMessageRequest` as `postMessage`, just with `selection` instead of
// `text`.
export async function postSelection(
	conversationId: string,
	txIds: string[],
): Promise<string> {
	const result = await withAuthRetry(() =>
		postMessageApiV1ConversationsConversationIdMessagesPost({
			path: { conversation_id: conversationId },
			body: { selection: { tx_ids: txIds } },
		}),
	);
	return unwrap(result).turn_id;
}

// Replacement-card pick (spec D33): same channel as `postSelection`, with
// `card_selection`. An empty list is the "No, gracias" decline.
export async function postCardSelection(
	conversationId: string,
	cardIds: string[],
): Promise<string> {
	const result = await withAuthRetry(() =>
		postMessageApiV1ConversationsConversationIdMessagesPost({
			path: { conversation_id: conversationId },
			body: { card_selection: { card_ids: cardIds } },
		}),
	);
	return unwrap(result).turn_id;
}

// The next three wrap the D1 routes proposed in this card's spec (`04` §3).
// They are not in the generated SDK yet: A2/A4 land the real routes, and
// `make client` regenerates typed functions to replace these by hand.
type TurnAccepted = { turn_id: string };

export async function postResume(conversationId: string): Promise<string> {
	const result = await withAuthRetry(() =>
		client.post<{ 202: TurnAccepted }, unknown>({
			url: "/api/v1/conversations/{conversation_id}/messages",
			path: { conversation_id: conversationId },
			body: { resume: "step_up" },
		}),
	);
	return unwrap(result).turn_id;
}

// Cancel of the agent OTP pause (spec D12, D16, D17): same channel as
// `postResume`. `409 cancel_invalid` means no pause is open.
export async function postStepUpCancel(
	conversationId: string,
): Promise<string> {
	const result = await withAuthRetry(() =>
		client.post<{ 202: TurnAccepted }, unknown>({
			url: "/api/v1/conversations/{conversation_id}/messages",
			path: { conversation_id: conversationId },
			body: { resume: "step_up_cancel" },
		}),
	);
	return unwrap(result).turn_id;
}

export type ConfirmationDecision = "confirm" | "cancel";

export async function postConfirmation(
	conversationId: string,
	tokenId: string,
	decision: ConfirmationDecision,
): Promise<string> {
	const result = await withAuthRetry(() =>
		client.post<{ 202: TurnAccepted }, unknown>({
			url: "/api/v1/conversations/{conversation_id}/confirmations/{token_id}",
			path: { conversation_id: conversationId, token_id: tokenId },
			body: { decision },
		}),
	);
	return unwrap(result).turn_id;
}

export async function verifyOtp(
	code: string,
	conversationId: string,
): Promise<void> {
	const exec = () =>
		client.post<{ 200: MeResponse }, unknown>({
			url: "/api/v1/auth/otp/verify",
			body: { code, conversation_id: conversationId },
		});
	const first = await exec();
	// A wrong code is a 401 `otp_invalid`, not an expired session: skip the
	// refresh-and-retry (it would burn extra of the step-up limit and end in the
	// re-login dialog). Only another 401 detail goes through `withAuthRetry`.
	if (statusOf(first) === 401 && errorCode(first.error) !== "otp_invalid") {
		unwrap(await withAuthRetry(exec));
		return;
	}
	unwrap(first);
}

// D4-B D3/D5: the staff SPA. `staffLogin` is the entry point (exempt from
// any retry, same as `login`); every other staff call goes through
// `withStaffAuth`, which sends a `401` straight to `/staff/login` with no
// refresh attempt -- an agent session's `/auth/refresh` answers `403`, not
// `401`, so `withAuthRetry`'s refresh-then-retry would never help here.
export async function staffLogin(
	body: StaffLoginRequest,
): Promise<StaffMeResponse> {
	const result = await staffLoginApiV1AuthStaffLoginPost({ body });
	return unwrap(result);
}

async function withStaffAuth<T>(
	exec: () => Promise<FetchResult<T>>,
): Promise<FetchResult<T>> {
	const result = await exec();
	if (statusOf(result) === 401) {
		window.location.assign("/staff/login");
	}
	return result;
}

// Mirrors `me()`: called only from a route's own `beforeLoad` guard, which
// decides the redirect itself, so this never also fires `withStaffAuth`'s
// 401 redirect.
export async function staffMe(): Promise<StaffMeResponse | null> {
	const result = await staffMeApiV1StaffMeGet();
	if (statusOf(result) === 401) {
		return null;
	}
	return unwrap(result);
}

// Ends the staff session (clears the staff cookie). A `401` here means the
// session is already gone, which is the outcome the caller wants anyway.
export async function staffLogout(): Promise<void> {
	const result = await staffLogoutApiV1StaffLogoutPost();
	if (statusOf(result) === 401) {
		return;
	}
	unwrap(result);
}

export async function listStaffHandoffs(): Promise<HandoffSummary[]> {
	const result = await withStaffAuth(() => listHandoffsApiV1StaffHandoffsGet());
	return unwrap(result);
}

export async function getStaffHandoff(
	handoffId: string,
): Promise<HandoffDetail> {
	const result = await withStaffAuth(() =>
		getHandoffApiV1StaffHandoffsHandoffIdGet({
			path: { handoff_id: handoffId },
		}),
	);
	return unwrap(result);
}

export async function claimStaffHandoff(
	handoffId: string,
): Promise<HandoffDetail> {
	const result = await withStaffAuth(() =>
		claimHandoffApiV1StaffHandoffsHandoffIdClaimPost({
			path: { handoff_id: handoffId },
		}),
	);
	return unwrap(result);
}

export async function returnStaffHandoff(
	handoffId: string,
): Promise<HandoffSummary> {
	const result = await withStaffAuth(() =>
		returnHandoffApiV1StaffHandoffsHandoffIdReturnPost({
			path: { handoff_id: handoffId },
		}),
	);
	return unwrap(result);
}

// The claimed conversation's messages so far, oldest first (D4-A).
export async function getStaffTranscript(
	conversationId: string,
): Promise<TranscriptMessage[]> {
	const result = await withStaffAuth(() =>
		listConversationMessagesApiV1StaffConversationsConversationIdMessagesGet({
			path: { conversation_id: conversationId },
		}),
	);
	return unwrap(result);
}

export async function postAgentMessage(
	conversationId: string,
	text: string,
): Promise<string> {
	const result = await withStaffAuth(() =>
		postConversationMessageApiV1StaffConversationsConversationIdMessagesPost({
			path: { conversation_id: conversationId },
			body: { text },
		}),
	);
	return unwrap(result).message_id;
}

/** `GET /staff/conversations` query (D7-A D19): every filter is optional and ANDed. */
export type StaffConversationQuery = NonNullable<
	ListConversationsApiV1StaffConversationsGetData["query"]
>;

// D7-A1 traceability console (read-only, masked data only): the list needs no
// `{id}` and the timeline uses `get_any_conversation`, so neither needs a claim.
export async function listStaffConversations(
	query: StaffConversationQuery,
): Promise<ConversationPage> {
	const result = await withStaffAuth(() =>
		listConversationsApiV1StaffConversationsGet({ query }),
	);
	return unwrap(result);
}

export async function getStaffConversationTimeline(
	conversationId: string,
): Promise<ConversationTimeline> {
	const result = await withStaffAuth(() =>
		getConversationTimelineApiV1StaffConversationsConversationIdTimelineGet({
			path: { conversation_id: conversationId },
		}),
	);
	return unwrap(result);
}

const CONVERSATION_STORAGE_KEY = "swip.conversation_id";

export const conversationStore = {
	get(): string | null {
		return window.sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
	},
	set(conversationId: string): void {
		window.sessionStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
	},
	clear(): void {
		window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
	},
};

/** `GET /staff/analytics/summary` query: every filter is optional and ANDed. */
export type AnalyticsQuery = NonNullable<
	GetAnalyticsSummaryApiV1StaffAnalyticsSummaryGetData["query"]
>;

// Re-exported so the analytics blocks import their data types from one place.
export type { AnalyticsSummary, Rate, RecentInteraction };

export async function getAnalyticsSummary(
	query: AnalyticsQuery,
): Promise<AnalyticsSummary> {
	const result = await withStaffAuth(() =>
		getAnalyticsSummaryApiV1StaffAnalyticsSummaryGet({ query }),
	);
	return unwrap(result);
}

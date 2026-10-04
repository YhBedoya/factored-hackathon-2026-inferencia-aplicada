import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import type { HandoffDetail } from "@/client";
import { AgentChat } from "@/components/staff/AgentChat";
import { PacketView } from "@/components/staff/PacketView";
import { StaffNav } from "@/components/staff/StaffNav";
import { Button } from "@/components/ui/button";
import {
	ApiError,
	getStaffHandoff,
	returnStaffHandoff,
	staffMe,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// D5/D20: same guard as `staff/index.tsx`.
export const Route = createFileRoute("/staff/handoffs/$handoffId")({
	beforeLoad: async () => {
		const agent = await staffMe();
		if (!agent) {
			throw redirect({ to: "/staff/login" });
		}
	},
	component: StaffHandoffDetailPage,
});

function StaffHandoffDetailPage() {
	const { t } = useI18n();
	const navigate = useNavigate();
	const { handoffId } = Route.useParams();
	const [detail, setDetail] = useState<HandoffDetail | null>(null);
	const [returning, setReturning] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		getStaffHandoff(handoffId)
			.then((result) => {
				if (cancelled) {
					return;
				}
				// A queued case is claimed only from the inbox's claim button;
				// opening its URL (a link, a reload, Back) never claims it.
				if (result.summary.status === "queued") {
					void navigate({ to: "/staff", replace: true });
					return;
				}
				setDetail(result);
			})
			.catch((error: unknown) => {
				if (!cancelled) {
					setErrorCode(error instanceof ApiError ? error.code : "generic");
				}
			});
		return () => {
			cancelled = true;
		};
	}, [handoffId, navigate]);

	async function handleReturn() {
		setReturning(true);
		setErrorCode(null);
		try {
			await returnStaffHandoff(handoffId);
			await navigate({ to: "/staff" });
		} catch (error) {
			setErrorCode(error instanceof ApiError ? error.code : "generic");
			setReturning(false);
		}
	}

	if (!detail) {
		return (
			<>
				<StaffNav />
				{errorCode ? (
					<p role="alert" className="px-6 py-10 text-sm text-alert">
						{t("errors.generic")}
					</p>
				) : (
					// Loading: the same two columns as the case, as placeholders.
					<div
						aria-busy="true"
						className="grid w-full gap-6 px-6 py-10 lg:px-10 lg:grid-cols-2 lg:items-start"
					>
						<div className="flex flex-col gap-3">
							<div className="h-4 w-40 animate-pulse rounded-2xl bg-card" />
							<div className="h-[60vh] animate-pulse rounded-2xl bg-card" />
							<div className="h-11 animate-pulse rounded-full bg-card" />
						</div>
						<div className="order-first h-[70vh] animate-pulse rounded-2xl bg-card lg:order-none" />
					</div>
				)}
			</>
		);
	}

	return (
		<>
			<StaffNav />
			<div className="flex w-full flex-1 flex-col gap-4 px-6 py-10 lg:px-10">
				{/* Wide screens: chat on the left, the case packet on the right
				    (kept in view, scrolling on its own, while the chat scrolls).
				    Narrow screens stack them, packet first. */}
				<div className="grid gap-6 lg:grid-cols-2 lg:items-start">
					<div className="flex flex-col gap-4">
						<AgentChat
							conversationId={detail.summary.conversation_id}
							reference={detail.summary.reference}
						/>
						<Button
							variant="outline"
							data-testid="return-handoff"
							className={cn(
								"h-10 self-start rounded-full border-muted-foreground px-[18px] font-semibold hover:border-foreground",
								returning && "opacity-45",
							)}
							disabled={returning}
							onClick={() => void handleReturn()}
						>
							{t(returning ? "staff.detail.returning" : "staff.detail.return")}
						</Button>
					</div>
					<div className="order-first lg:sticky lg:top-22 lg:order-none lg:max-h-[calc(100vh-112px)] lg:overflow-y-auto">
						<PacketView summary={detail.summary} packet={detail.packet} />
					</div>
				</div>
				{errorCode && (
					<p role="alert" className="text-sm text-alert">
						{t("errors.generic")}
					</p>
				)}
			</div>
		</>
	);
}

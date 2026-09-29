import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import type { HandoffDetail } from "@/client";
import { AgentChat } from "@/components/staff/AgentChat";
import { PacketView } from "@/components/staff/PacketView";
import { Button } from "@/components/ui/button";
import {
	ApiError,
	claimStaffHandoff,
	getStaffHandoff,
	returnStaffHandoff,
	staffMe,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
	const [claiming, setClaiming] = useState(false);
	const [returning, setReturning] = useState(false);
	const [errorCode, setErrorCode] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		getStaffHandoff(handoffId)
			.then((result) => {
				if (!cancelled) {
					setDetail(result);
				}
			})
			.catch((error: unknown) => {
				if (!cancelled) {
					setErrorCode(error instanceof ApiError ? error.code : "generic");
				}
			});
		return () => {
			cancelled = true;
		};
	}, [handoffId]);

	async function handleClaim() {
		setClaiming(true);
		setErrorCode(null);
		try {
			const result = await claimStaffHandoff(handoffId);
			setDetail(result);
		} catch (error) {
			setErrorCode(error instanceof ApiError ? error.code : "generic");
		} finally {
			setClaiming(false);
		}
	}

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
		return errorCode ? (
			<p role="alert" className="px-6 py-10 text-sm text-alert">
				{t("errors.generic")}
			</p>
		) : null;
	}

	return (
		<div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-6 py-10">
			{detail.summary.status === "queued" ? (
				<Button
					data-testid="claim-handoff"
					disabled={claiming}
					onClick={() => void handleClaim()}
				>
					{t("staff.detail.claim")}
				</Button>
			) : (
				<>
					<PacketView packet={detail.packet} />
					<AgentChat conversationId={detail.summary.conversation_id} />
					<Button
						variant="outline"
						data-testid="return-handoff"
						disabled={returning}
						onClick={() => void handleReturn()}
					>
						{t("staff.detail.return")}
					</Button>
				</>
			)}
			{errorCode && (
				<p role="alert" className="text-sm text-alert">
					{t("errors.generic")}
				</p>
			)}
		</div>
	);
}

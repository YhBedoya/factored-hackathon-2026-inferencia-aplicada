import { BellIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";

import { useHomeAlerts } from "./alerts";

// The bell: the home's alerts (`useHomeAlerts`) as notifications. "Read" is
// local state only, nothing is stored; a click on one asks Cardy about it.
export function NotificationsMenu({
	onAsk,
}: {
	onAsk: (prompt: string) => void;
}) {
	const { t } = useI18n();
	const { alerts, loading, failed } = useHomeAlerts();
	const [open, setOpen] = useState(false);
	const [read, setRead] = useState(false);
	const rootRef = useRef<HTMLDivElement>(null);
	const unread = read ? 0 : alerts.length;

	useEffect(() => {
		if (!open) {
			return;
		}
		function onPointer(event: PointerEvent) {
			if (!rootRef.current?.contains(event.target as Node)) {
				setOpen(false);
			}
		}
		function onKey(event: KeyboardEvent) {
			if (event.key === "Escape") {
				setOpen(false);
			}
		}
		document.addEventListener("pointerdown", onPointer);
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("pointerdown", onPointer);
			document.removeEventListener("keydown", onKey);
		};
	}, [open]);

	return (
		<div ref={rootRef} className="relative">
			<button
				type="button"
				data-testid="home-bell"
				aria-label={t("home.notif.open")}
				aria-expanded={open}
				onClick={() => setOpen(!open)}
				className={`relative grid size-[42px] cursor-pointer place-items-center rounded-full border border-border text-foreground hover:bg-card ${open ? "bg-card" : ""}`}
			>
				<BellIcon className="size-[18px]" aria-hidden="true" />
				{unread > 0 && (
					<span
						data-testid="home-bell-count"
						className="absolute -top-[3px] -right-[3px] grid h-[18px] min-w-[18px] place-items-center rounded-full bg-gold px-[5px] text-[11px] font-semibold text-bg"
					>
						{unread}
					</span>
				)}
			</button>
			{open && (
				<div
					data-testid="home-notifications"
					className="absolute top-14 right-0 z-30 w-[380px] overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_56px_rgba(0,0,0,.6)]"
				>
					<div className="flex items-center justify-between border-b border-border px-[18px] py-4">
						<span className="font-semibold">{t("home.notif.title")}</span>
						{alerts.length > 0 && (
							<button
								type="button"
								onClick={() => setRead(true)}
								className="cursor-pointer p-1 text-[13px] font-semibold text-cyan"
							>
								{t("home.notif.mark_read")}
							</button>
						)}
					</div>
					{loading && (
						<div
							role="status"
							aria-label={t("home.loading")}
							className="m-4 h-10 animate-pulse rounded-lg bg-muted"
						/>
					)}
					{!loading && failed && (
						<p role="alert" className="px-[18px] py-4 text-sm text-alert">
							{t("home.error")}
						</p>
					)}
					{!loading && !failed && alerts.length === 0 && (
						<p className="px-[18px] py-4 text-sm text-muted-foreground">
							{t("home.alerts.empty")}
						</p>
					)}
					{alerts.map((alert) => (
						<button
							key={alert.key}
							type="button"
							data-testid="home-alert"
							onClick={() => {
								setOpen(false);
								onAsk(alert.prompt);
							}}
							className={`flex w-full cursor-pointer gap-3 border-b border-border px-[18px] py-3.5 text-left text-sm last:border-b-0 hover:bg-muted ${read ? "" : "bg-muted/60"}`}
						>
							<span
								aria-hidden="true"
								className={`mt-1.5 size-2 flex-none rounded-full ${read ? "bg-border" : "bg-cyan"}`}
							/>
							<span className="flex flex-col gap-0.5">
								<span className="font-semibold">{alert.text}</span>
								<span className="text-[13px] text-cyan">
									{t("home.notif.ask")}
								</span>
							</span>
						</button>
					))}
				</div>
			)}
		</div>
	);
}

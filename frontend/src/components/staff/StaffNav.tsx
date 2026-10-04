import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";

import { LanguageToggle } from "@/components/layout/LanguageToggle";
import { staffLogout, staffMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const STAFF_ME_QUERY_KEY = ["staff", "me"] as const;

const TAB =
	"flex h-16 items-center border-b-2 text-[15px] font-semibold transition-colors";
const TAB_ACTIVE = "border-cyan text-foreground";
const TAB_IDLE =
	"border-transparent text-muted-foreground hover:text-foreground";

// The "Swip" wordmark plus the gold "Staff" badge, shared by `StaffNav` and
// the analytics header.
export function StaffLogo() {
	const { t } = useI18n();
	return (
		<>
			<span className="flex items-center gap-2 font-heading text-[22px] font-bold tracking-tight">
				<span aria-hidden="true" className="size-2.5 rounded-[3px] bg-cyan" />
				Swip
			</span>
			<span className="rounded-full border border-gold px-2.5 py-0.5 text-xs font-semibold tracking-[0.06em] text-gold uppercase">
				{t("staff.nav.badge")}
			</span>
		</>
	);
}

// The staff top bar ("Swip Staff Bandeja" design), shared by the inbox, the
// case screen and the conversation screens. `AppShell` hides its own header
// on those routes, so the language toggle lives here.
export function StaffNav() {
	const { t } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const { data: staff } = useQuery({
		queryKey: STAFF_ME_QUERY_KEY,
		queryFn: staffMe,
	});
	const onConversations = pathname.startsWith("/staff/conversations");

	async function handleLogout() {
		await staffLogout();
		queryClient.removeQueries({ queryKey: ["staff"] });
		await navigate({ to: "/staff/login" });
	}

	return (
		<nav
			aria-label={t("staff.nav.label")}
			className="sticky top-0 z-20 border-b border-border bg-bg/95 backdrop-blur-md"
		>
			<div className="mx-auto flex h-16 max-w-[1120px] items-center gap-3.5 px-6 lg:px-10">
				<StaffLogo />
				<div className="ml-6 flex h-16 items-center gap-6">
					<Link
						to="/staff"
						aria-current={onConversations ? undefined : "page"}
						className={cn(TAB, onConversations ? TAB_IDLE : TAB_ACTIVE)}
					>
						{t("staff.inbox.title")}
					</Link>
					<Link
						to="/staff/conversations"
						aria-current={onConversations ? "page" : undefined}
						className={cn(TAB, onConversations ? TAB_ACTIVE : TAB_IDLE)}
					>
						{t("staff.conversations.nav_link")}
					</Link>
					{staff?.role === "admin" && (
						<Link
							to="/staff/analytics"
							data-testid="analytics-nav-link"
							className={cn(TAB, TAB_IDLE)}
						>
							{t("staff.analytics.nav_link")}
						</Link>
					)}
				</div>
				<div className="flex-1" />
				<LanguageToggle />
				{staff && (
					<div className="flex items-center gap-2.5 rounded-full border border-border py-1 pr-3.5 pl-1">
						<span
							aria-hidden="true"
							className="grid size-8 place-items-center rounded-full border border-cyan bg-card font-heading text-sm text-cyan"
						>
							{staff.display_name.charAt(0).toUpperCase()}
						</span>
						<span className="flex flex-col leading-tight">
							<span className="text-sm font-semibold">
								{staff.display_name}
							</span>
							<span className="text-xs text-muted-foreground">
								{t(`staff.role.${staff.role}`)}
							</span>
						</span>
					</div>
				)}
				<button
					type="button"
					data-testid="staff-logout"
					onClick={handleLogout}
					className="cursor-pointer px-1 py-2 text-sm font-semibold text-muted-foreground hover:text-foreground"
				>
					{t("shell.logout")}
				</button>
			</div>
		</nav>
	);
}

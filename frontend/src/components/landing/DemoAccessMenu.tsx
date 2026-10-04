import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { cn } from "cn";
import {
	BookOpenIcon,
	CheckIcon,
	CodeIcon,
	CopyIcon,
	KeyRoundIcon,
	ShieldCheckIcon,
	UserRoundIcon,
} from "lucide-react";
import { useState } from "react";

import { ME_QUERY_KEY } from "@/components/layout/useLogout";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	type DemoChip,
	type DemoPersona,
	demoLoginCustomer,
	demoLoginStaff,
	getDemoCatalog,
} from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

const DEMO_CATALOG_QUERY_KEY = ["demo-catalog"] as const;

/**
 * ADR-036: the judges' quick access, top-left on the landing. The button only
 * renders when `GET /demo/catalog` answers (the backend runs with
 * `DEMO_QUICK_LOGIN=true`); otherwise the route is a 404 and nothing shows.
 * The panel logs in as a curated demo persona (lands on `/home`) or as the
 * seeded admin (lands on `/staff`) without any password reaching the browser.
 */
export function DemoAccessMenu() {
	const { t } = useI18n();
	const [open, setOpen] = useState(false);
	const catalog = useQuery({
		queryKey: DEMO_CATALOG_QUERY_KEY,
		queryFn: getDemoCatalog,
		retry: false,
		staleTime: Number.POSITIVE_INFINITY,
	});

	if (!catalog.data) {
		return null;
	}

	return (
		<>
			<Button
				type="button"
				variant="outline"
				className="h-10 rounded-full px-4 text-sm font-semibold"
				data-testid="demo-access-button"
				aria-label={t("landing.demo.button")}
				onClick={() => setOpen(true)}
			>
				<KeyRoundIcon aria-hidden />
				<span className="hidden sm:inline">{t("landing.demo.button")}</span>
			</Button>
			<Dialog open={open} onOpenChange={setOpen}>
				<DialogContent
					data-testid="demo-access-dialog"
					className="max-h-[90vh] overflow-y-auto sm:max-w-xl"
				>
					<DialogHeader>
						<DialogTitle>{t("landing.demo.title")}</DialogTitle>
						<DialogDescription>{t("landing.demo.intro")}</DialogDescription>
					</DialogHeader>
					<CustomerSection personas={catalog.data.personas} />
					<StaffSection />
					<ExtrasSection
						otpCode={catalog.data.otp_code}
						repo={catalog.data.links.repo}
						docs={catalog.data.links.docs}
					/>
				</DialogContent>
			</Dialog>
		</>
	);
}

function SectionTitle({
	icon,
	children,
}: {
	icon: React.ReactNode;
	children: React.ReactNode;
}) {
	return (
		<h3 className="flex items-center gap-2 text-sm font-semibold">
			{icon}
			{children}
		</h3>
	);
}

function CustomerSection({ personas }: { personas: DemoPersona[] }) {
	const { t, lang } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [pending, setPending] = useState(false);
	const [error, setError] = useState(false);
	const selected = personas.find((p) => p.persona_id === selectedId) ?? null;

	async function handleLogin() {
		if (!selected) {
			return;
		}
		setPending(true);
		setError(false);
		try {
			await demoLoginCustomer(selected.persona_id);
			await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
			await navigate({ to: "/home" });
		} catch {
			setError(true);
		} finally {
			setPending(false);
		}
	}

	return (
		<section className="flex flex-col gap-3" aria-labelledby="demo-customer">
			<SectionTitle icon={<UserRoundIcon className="size-4" aria-hidden />}>
				<span id="demo-customer">{t("landing.demo.customer.title")}</span>
			</SectionTitle>
			<p className="text-muted-foreground text-xs">
				{t("landing.demo.customer.hint")}
			</p>
			<div
				className="flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-lg border p-1.5"
				data-testid="demo-persona-list"
			>
				{personas.map((persona) => {
					const active = persona.persona_id === selectedId;
					return (
						<button
							key={persona.persona_id}
							type="button"
							aria-pressed={active}
							data-testid="demo-persona"
							onClick={() => setSelectedId(persona.persona_id)}
							className={cn(
								"flex flex-col gap-1 rounded-md border px-3 py-2 text-left transition-colors",
								active
									? "border-primary bg-primary/10"
									: "border-transparent hover:bg-muted",
							)}
						>
							<span className="flex items-center gap-2 text-sm font-medium">
								<span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
									{persona.country}
								</span>
								{persona.display_name}
							</span>
							<span className="flex flex-wrap gap-1">
								<Chip>
									{persona.card_count === 1
										? t("landing.demo.card")
										: t("landing.demo.cards", {
												count: String(persona.card_count),
											})}
								</Chip>
								{persona.chips.map((chip) => (
									<Chip key={chip}>{t(chipKey(chip))}</Chip>
								))}
							</span>
							<span className="text-muted-foreground text-xs">
								{persona.purpose[lang]}
							</span>
						</button>
					);
				})}
			</div>
			{selected && (
				<div className="flex flex-col gap-1.5" data-testid="demo-prompts">
					<p className="text-xs font-medium">{t("landing.demo.prompts")}</p>
					{selected.prompts[lang].map((prompt) => (
						<div
							key={prompt}
							className="flex items-center justify-between gap-2 rounded-md bg-muted px-3 py-1.5 text-xs"
						>
							<span>{prompt}</span>
							<CopyButton value={prompt} />
						</div>
					))}
				</div>
			)}
			<Button
				type="button"
				disabled={!selected || pending}
				onClick={handleLogin}
				data-testid="demo-customer-login"
			>
				{selected
					? t("landing.demo.customer.login", { name: selected.display_name })
					: t("landing.demo.customer.pick")}
			</Button>
			{error && (
				<p role="alert" className="text-destructive text-xs">
					{t("landing.demo.error")}
				</p>
			)}
		</section>
	);
}

function StaffSection() {
	const { t } = useI18n();
	const navigate = useNavigate();
	const [pending, setPending] = useState(false);
	const [error, setError] = useState(false);

	async function handleLogin() {
		setPending(true);
		setError(false);
		try {
			await demoLoginStaff();
			await navigate({ to: "/staff" });
		} catch {
			setError(true);
		} finally {
			setPending(false);
		}
	}

	return (
		<section
			className="flex flex-col gap-3 border-t pt-4"
			aria-labelledby="demo-staff"
		>
			<SectionTitle icon={<ShieldCheckIcon className="size-4" aria-hidden />}>
				<span id="demo-staff">{t("landing.demo.staff.title")}</span>
			</SectionTitle>
			<p className="text-muted-foreground text-xs">
				{t("landing.demo.staff.hint")}
			</p>
			<Button
				type="button"
				variant="outline"
				disabled={pending}
				onClick={handleLogin}
				data-testid="demo-staff-login"
			>
				{t("landing.demo.staff.login")}
			</Button>
			{error && (
				<p role="alert" className="text-destructive text-xs">
					{t("landing.demo.error")}
				</p>
			)}
		</section>
	);
}

function ExtrasSection({
	otpCode,
	repo,
	docs,
}: {
	otpCode: string | null;
	repo: string | null;
	docs: string | null;
}) {
	const { t } = useI18n();
	if (!otpCode && !repo && !docs) {
		return null;
	}
	return (
		<section className="flex flex-col gap-3 border-t pt-4">
			{otpCode && (
				<div className="flex items-center justify-between gap-2">
					<div>
						<p className="text-sm font-semibold">{t("landing.demo.otp")}</p>
						<p className="text-muted-foreground text-xs">
							{t("landing.demo.otp.hint")}
						</p>
					</div>
					<span className="flex items-center gap-1">
						<code
							className="rounded bg-muted px-2 py-1 font-mono text-sm"
							data-testid="demo-otp"
						>
							{otpCode}
						</code>
						<CopyButton value={otpCode} />
					</span>
				</div>
			)}
			{(repo || docs) && (
				<div className="flex flex-wrap items-center gap-2">
					<span className="text-sm font-semibold">
						{t("landing.demo.links")}
					</span>
					{repo && (
						<Button asChild variant="ghost" size="sm">
							<a href={repo} target="_blank" rel="noreferrer">
								<CodeIcon aria-hidden />
								{t("landing.demo.links.repo")}
							</a>
						</Button>
					)}
					{docs && (
						<Button asChild variant="ghost" size="sm">
							<a href={docs} target="_blank" rel="noreferrer">
								<BookOpenIcon aria-hidden />
								{t("landing.demo.links.docs")}
							</a>
						</Button>
					)}
				</div>
			)}
		</section>
	);
}

function Chip({ children }: { children: React.ReactNode }) {
	return (
		<span className="rounded-full border px-2 py-0.5 text-[10px] leading-tight">
			{children}
		</span>
	);
}

function chipKey(chip: DemoChip): TKey {
	return `landing.demo.chip.${chip}` as TKey;
}

function CopyButton({ value }: { value: string }) {
	const { t } = useI18n();
	const [copied, setCopied] = useState(false);

	async function handleCopy(event: React.MouseEvent) {
		event.stopPropagation();
		try {
			await navigator.clipboard.writeText(value);
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1500);
		} catch {
			// Clipboard blocked (no secure context): the text is still on screen.
		}
	}

	return (
		<Button
			type="button"
			variant="ghost"
			size="icon-xs"
			aria-label={copied ? t("landing.demo.copied") : t("landing.demo.copy")}
			title={copied ? t("landing.demo.copied") : t("landing.demo.copy")}
			onClick={handleCopy}
		>
			{copied ? <CheckIcon aria-hidden /> : <CopyIcon aria-hidden />}
		</Button>
	);
}

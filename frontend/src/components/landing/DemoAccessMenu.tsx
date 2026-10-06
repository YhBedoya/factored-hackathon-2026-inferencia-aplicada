import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { cn } from "cn";
import {
	BookOpenIcon,
	CheckIcon,
	ChevronDownIcon,
	CodeIcon,
	CopyIcon,
	KeyRoundIcon,
	ShieldCheckIcon,
	UserRoundIcon,
	WrenchIcon,
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	type DemoChip,
	type DemoLocked,
	type DemoPersona,
	demoLoginCustomer,
	demoLoginStaff,
	getDemoCatalog,
	setDemoCode,
} from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

const DEMO_CATALOG_QUERY_KEY = ["demo-catalog"] as const;

/**
 * ADR-036: the judges' quick access, top-left on the landing. The button only
 * renders when `GET /demo/catalog` answers (the backend runs with
 * `DEMO_QUICK_LOGIN=true`); otherwise the route is a 404 and nothing shows.
 * Until this tab has sent the right access code (emailed to the judges) the
 * catalog is locked and the panel asks for it; then it logs in as a curated
 * demo persona (lands on `/home`) or as the seeded admin (lands on `/staff`)
 * without any password reaching the browser.
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
					{"locked" in catalog.data ? (
						<CodeForm
							reason={catalog.data.reason}
							onSubmit={async (code) => {
								setDemoCode(code);
								await catalog.refetch();
							}}
						/>
					) : (
						<>
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
						</>
					)}
				</DialogContent>
			</Dialog>
		</>
	);
}

// The gate in front of the panel: one field for the judges' access code.
function CodeForm({
	reason,
	onSubmit,
}: {
	reason: DemoLocked["reason"];
	onSubmit: (code: string) => Promise<void>;
}) {
	const { t } = useI18n();
	const [code, setCode] = useState("");
	const [pending, setPending] = useState(false);

	async function handleSubmit(event: React.FormEvent) {
		event.preventDefault();
		setPending(true);
		try {
			await onSubmit(code);
		} finally {
			setPending(false);
		}
	}

	return (
		<form
			onSubmit={handleSubmit}
			className="flex flex-col gap-3"
			data-testid="demo-code-form"
		>
			<DialogHeader>
				<DialogTitle>{t("landing.demo.title")}</DialogTitle>
				<DialogDescription>{t("landing.demo.code.hint")}</DialogDescription>
			</DialogHeader>
			<Label htmlFor="demo-code">{t("landing.demo.code.label")}</Label>
			<Input
				id="demo-code"
				type="text"
				autoComplete="off"
				autoCapitalize="none"
				spellCheck={false}
				placeholder={t("landing.demo.code.placeholder")}
				value={code}
				onChange={(event) => setCode(event.target.value)}
				data-testid="demo-code-input"
			/>
			{reason !== "required" && (
				<p role="alert" className="text-destructive text-xs">
					{t(
						reason === "throttled"
							? "landing.demo.code.throttled"
							: "landing.demo.code.invalid",
					)}
				</p>
			)}
			<Button
				type="submit"
				disabled={!code.trim() || pending}
				data-testid="demo-code-submit"
			>
				{t("landing.demo.code.submit")}
			</Button>
		</form>
	);
}

// Each part of the panel is its own collapsible card, closed when the panel
// opens: the header (icon, title, hint) toggles its body. Several can be
// open at once.
function DemoSection({
	id,
	icon,
	title,
	hint,
	children,
}: {
	id: string;
	icon: React.ReactNode;
	title: string;
	hint: string;
	children: React.ReactNode;
}) {
	const [open, setOpen] = useState(false);
	const bodyId = `${id}-body`;
	return (
		<section
			aria-labelledby={id}
			data-testid={id}
			className="overflow-hidden rounded-xl border bg-card"
		>
			<h3>
				<button
					type="button"
					id={id}
					aria-expanded={open}
					aria-controls={bodyId}
					data-testid={`${id}-toggle`}
					onClick={() => setOpen((value) => !value)}
					className={cn(
						"flex w-full items-center gap-3 bg-muted/50 px-4 py-3 text-left transition-colors hover:bg-muted",
						open && "border-b",
					)}
				>
					<span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
						{icon}
					</span>
					<span className="flex flex-1 flex-col gap-0.5">
						<span className="text-sm font-semibold">{title}</span>
						<span className="text-muted-foreground text-xs font-normal">
							{hint}
						</span>
					</span>
					<ChevronDownIcon
						aria-hidden
						className={cn(
							"size-4 shrink-0 text-muted-foreground transition-transform",
							open && "rotate-180",
						)}
					/>
				</button>
			</h3>
			{open && (
				<div id={bodyId} className="flex flex-col gap-3 p-4">
					{children}
				</div>
			)}
		</section>
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
		<DemoSection
			id="demo-customer"
			icon={<UserRoundIcon className="size-4" aria-hidden />}
			title={t("landing.demo.customer.title")}
			hint={t("landing.demo.customer.hint")}
		>
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
		</DemoSection>
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
		<DemoSection
			id="demo-staff"
			icon={<ShieldCheckIcon className="size-4" aria-hidden />}
			title={t("landing.demo.staff.title")}
			hint={t("landing.demo.staff.hint")}
		>
			<Button
				type="button"
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
		</DemoSection>
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
		<DemoSection
			id="demo-tools"
			icon={<WrenchIcon className="size-4" aria-hidden />}
			title={t("landing.demo.tools.title")}
			hint={t("landing.demo.tools.hint")}
		>
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
				<div className="flex flex-wrap items-center gap-2 border-t pt-3">
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
		</DemoSection>
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

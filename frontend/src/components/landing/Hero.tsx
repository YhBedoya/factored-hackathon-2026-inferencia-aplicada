import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

import { SoonButton } from "./SoonButton";

// A gold EMV chip: gold gradient plate with the contact pad lines drawn in
// the background colour, so it reads on both the dark and the cyan card.
function Chip() {
	return (
		<span className="relative block h-[22%] w-[15%] min-w-9 overflow-hidden rounded-[22%] bg-gradient-to-br from-gold via-gold/85 to-gold/60 shadow-[inset_0_1px_0_rgb(255_255_255/0.45),0_1px_2px_rgb(0_0_0/0.35)] ring-1 ring-background/25">
			<svg
				aria-hidden="true"
				viewBox="0 0 40 30"
				preserveAspectRatio="none"
				className="absolute inset-0 size-full text-background/35"
				fill="none"
				stroke="currentColor"
				strokeWidth="1.2"
			>
				<path d="M0 10h13M0 20h13M27 10h13M27 20h13M13 0v30M27 0v30" />
				<rect x="13" y="8" width="14" height="14" rx="3" />
			</svg>
		</span>
	);
}

function CardFace({
	kind,
	mask,
	className,
}: {
	kind: string;
	mask: string;
	className: string;
}) {
	return (
		<div
			aria-hidden="true"
			className={`absolute flex aspect-[1.586/1] w-[70%] flex-col justify-between rounded-2xl p-[6%_7%] shadow-2xl ${className}`}
		>
			<div className="flex items-center justify-between">
				<span className="font-heading text-lg font-bold lg:text-2xl">Swip</span>
				<span className="text-xs font-semibold tracking-widest uppercase lg:text-sm">
					{kind}
				</span>
			</div>
			<Chip />
			<span className="font-semibold tracking-[0.12em] lg:text-xl">{mask}</span>
		</div>
	);
}

function HeroVisual() {
	const { t } = useI18n();
	return (
		<div className="relative mx-auto aspect-[1.15/1] w-full max-w-[680px]">
			<span
				aria-hidden="true"
				className="absolute top-[30%] left-[30%] size-[3px] rounded-full bg-gold opacity-90"
			/>
			<span
				aria-hidden="true"
				className="absolute top-[20%] left-[80%] size-[3px] rounded-full bg-gold opacity-60"
			/>
			<CardFace
				kind={t("landing.hero.credit")}
				mask="•••• 4417"
				className="top-[10%] left-[2%] -rotate-6 border border-cyan/40 bg-muted bg-gradient-to-br from-cyan/35 via-cyan/15 to-transparent text-foreground"
			/>
			<CardFace
				kind={t("landing.hero.debit")}
				mask="•••• 0821"
				className="top-[32%] left-[26%] rotate-3 bg-cyan text-background"
			/>
			<div className="absolute right-0 bottom-0 flex w-[min(300px,80%)] flex-col gap-2 rounded-2xl border border-border bg-card p-4 shadow-2xl lg:w-[min(360px,80%)] lg:p-5">
				<span className="flex items-center gap-2 text-sm font-semibold lg:text-base">
					<span
						aria-hidden="true"
						className="grid size-6 place-items-center rounded-full border border-cyan bg-cyan/20 font-heading text-xs text-cyan"
					>
						C
					</span>
					{t("landing.hero.bubbleName")}
				</span>
				<p className="text-sm lg:text-base">{t("landing.hero.bubble")}</p>
			</div>
		</div>
	);
}

export function Hero() {
	const { t } = useI18n();
	return (
		<header
			id="inicio"
			className="mx-auto grid w-full max-w-6xl flex-1 content-center items-center gap-12 px-4 py-12 sm:px-8 md:grid-cols-2 md:py-24 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-10"
		>
			<div className="flex flex-col items-start gap-6 lg:gap-8">
				<h1 className="flex items-center gap-4 font-heading text-8xl leading-none font-bold tracking-tight md:gap-6 md:text-9xl lg:gap-7 lg:text-[10rem]">
					<span
						aria-hidden="true"
						className="size-8 rounded-[8px] bg-cyan md:size-10 lg:size-12 lg:rounded-[10px]"
					/>
					Swip
				</h1>
				<p className="max-w-[540px] text-2xl text-pretty text-foreground md:text-3xl lg:max-w-[620px] lg:text-4xl">
					{t("landing.hero.body")}
				</p>
				<div className="mt-2 flex flex-wrap gap-3">
					<SoonButton label={t("landing.hero.order")} large />
					<Button
						asChild
						variant="outline"
						className="h-12 rounded-full px-7 text-base font-semibold lg:h-14 lg:px-8 lg:text-lg"
					>
						<Link to="/" search={{ login: true }}>
							{t("landing.hero.meet")}
						</Link>
					</Button>
				</div>
			</div>
			<HeroVisual />
		</header>
	);
}

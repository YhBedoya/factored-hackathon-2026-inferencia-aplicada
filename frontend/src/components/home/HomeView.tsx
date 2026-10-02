import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Footer } from "@/components/landing/Footer";
import { ME_QUERY_KEY } from "@/components/layout/useLogout";
import { me } from "@/lib/api";
import { type TKey, useI18n } from "@/lib/i18n";

import { CardyPanel, type CardyPanelState } from "./CardyPanel";
import { HomeNav } from "./HomeNav";
import { HomeSidebar } from "./HomeSidebar";
import { MyCardsSection } from "./MyCardsSection";
import { useHomeCards } from "./queries";
import { TransactionsSection } from "./TransactionsSection";

const LOCALES = { es: "es", pt: "pt-BR" } as const;

// The banking home ("Swip Panel" design, `docs/design/home/SwipPanel-v1.html`),
// desktop only. Every figure comes from `/api/v1/me/*`; this view only owns
// the UI state: the selected card, hidden balances and the Cardy panel.
export function HomeView() {
	const { t, lang } = useI18n();
	const { data: customer } = useQuery({
		queryKey: ME_QUERY_KEY,
		queryFn: me,
		retry: false,
	});
	const home = useHomeCards();
	const [selectedId, setSelectedId] = useState<string | undefined>();
	const [hideBalances, setHideBalances] = useState(false);
	const [cardy, setCardy] = useState<CardyPanelState>("closed");
	const [prefill, setPrefill] = useState<string | undefined>();

	const name = customer?.display_name;
	const cardId = selectedId ?? home.cards[0]?.card_id;
	const card = home.cards.find((c) => c.card_id === cardId);
	// The header's date is presentation only, in the UI language.
	const today = new Intl.DateTimeFormat(LOCALES[lang], {
		dateStyle: "full",
	}).format(new Date());

	function ask(prompt: string) {
		setPrefill(prompt);
		setCardy("open");
	}

	function openCardy() {
		setPrefill(undefined);
		setCardy("open");
	}

	return (
		<div className="flex min-h-svh min-w-[1100px] flex-col">
			<HomeNav name={name} onAsk={ask} />
			<div className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col gap-8 px-10 pt-12 pb-[120px]">
				<header className="flex flex-col gap-2">
					<span className="text-sm font-semibold text-muted-foreground first-letter:uppercase">
						{today}
					</span>
					<h1 className="font-heading text-[44px] leading-[1.1] font-bold tracking-tight">
						{name && (
							<>
								<span className="text-cyan">{name}</span>
								{t("home.header.rest")}
							</>
						)}
					</h1>
				</header>
				<div className="grid grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] items-start gap-6">
					<div className="flex flex-col gap-6">
						<MyCardsSection
							home={home}
							selectedId={cardId}
							onSelect={setSelectedId}
							hideBalances={hideBalances}
							onToggleHide={() => setHideBalances(!hideBalances)}
						/>
						<TransactionsSection
							key={cardId}
							card={card}
							cardName={card ? t(`home.cards.name.${card.kind}` as TKey) : ""}
							hideBalances={hideBalances}
							onAsk={ask}
						/>
					</div>
					<HomeSidebar
						name={name}
						card={card}
						details={cardId ? home.details[cardId] : undefined}
						onAsk={ask}
						onOpenCardy={openCardy}
					/>
				</div>
			</div>
			<Footer />
			<CardyPanel
				state={cardy}
				prefill={prefill}
				onOpen={openCardy}
				onMinimize={() => setCardy("minimized")}
				onClose={() => setCardy("closed")}
			/>
		</div>
	);
}

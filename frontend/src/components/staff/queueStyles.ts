import type { HandoffSummary } from "@/client";

// Each queue keeps one brand color ("Swip Staff Bandeja" design): Fraudes
// is the alert red, Reclamos gold, Atención cyan, Cobranza neutral. The bar
// marks an inbox row; the chip is the case screen's solid queue badge.
export const QUEUE_BAR: Record<HandoffSummary["queue"], string> = {
	atencion: "bg-cyan",
	cobranza: "bg-muted-foreground",
	fraudes: "bg-alert",
	reclamos: "bg-gold",
};

export const QUEUE_CHIP: Record<HandoffSummary["queue"], string> = {
	atencion: "bg-cyan text-bg",
	cobranza: "bg-muted-foreground text-bg",
	fraudes: "bg-alert text-bg",
	reclamos: "bg-gold text-bg",
};

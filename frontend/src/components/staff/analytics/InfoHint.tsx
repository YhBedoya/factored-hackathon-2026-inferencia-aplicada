import { InfoIcon } from "lucide-react";
import { Tooltip } from "radix-ui";

/**
 * The ⓘ next to a KPI or panel title: hover or focus shows how to read the
 * number. The content is portalled so the panel's overflow never clips it.
 */
export function InfoHint({ label, text }: { label: string; text: string }) {
	return (
		<Tooltip.Provider delayDuration={150}>
			<Tooltip.Root>
				<Tooltip.Trigger asChild>
					<button
						type="button"
						aria-label={label}
						className="inline-flex shrink-0 text-muted-foreground hover:text-foreground focus-visible:text-foreground"
					>
						<InfoIcon className="size-3.5" aria-hidden />
					</button>
				</Tooltip.Trigger>
				<Tooltip.Portal>
					<Tooltip.Content
						side="bottom"
						align="start"
						sideOffset={4}
						collisionPadding={8}
						className="z-50 max-w-xs rounded-md bg-foreground px-3 py-2 text-xs leading-snug font-normal text-background shadow-md"
					>
						{text}
					</Tooltip.Content>
				</Tooltip.Portal>
			</Tooltip.Root>
		</Tooltip.Provider>
	);
}

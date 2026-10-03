import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { PickerOption } from "@/lib/sse";

type QuickRepliesProps = {
	options: PickerOption[];
	/** Sends the clicked label as ordinary text, exactly as if typed (D5). */
	onSelect: (label: string) => void;
};

/** `ui.quick_replies`: fixed-choice chips for a clarification slot (D4). */
export function QuickReplies({ options, onSelect }: QuickRepliesProps) {
	const [clicked, setClicked] = useState(false);

	function handleClick(label: string) {
		setClicked(true);
		onSelect(label);
	}

	return (
		<div className="mt-2 flex flex-wrap gap-2">
			{options.map((option) => (
				<Button
					key={option.label}
					type="button"
					variant="secondary"
					size="sm"
					data-testid="quick-reply-option"
					disabled={clicked}
					onClick={() => handleClick(option.label)}
				>
					{option.label}
				</Button>
			))}
		</div>
	);
}

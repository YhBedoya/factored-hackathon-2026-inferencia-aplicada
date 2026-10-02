import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n";

type ComposerProps = {
	/** Gated on the last turn's `done`, never on the stream's own readyState (D12). */
	disabled: boolean;
	onSend: (text: string) => void;
	/** A non-empty change replaces the input value; it is never sent on its own. */
	prefill?: string;
};

/** The message input. A picker/chip click reuses `onSend` with its label (D5). */
export function Composer({ disabled, onSend, prefill }: ComposerProps) {
	const { t } = useI18n();
	const [value, setValue] = useState("");
	const inputRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		if (prefill) {
			setValue(prefill);
		}
	}, [prefill]);

	// A disabled input drops focus, so give it back each time the turn ends
	// (and on mount): the customer types the next message without clicking.
	useEffect(() => {
		if (!disabled) {
			inputRef.current?.focus();
		}
	}, [disabled]);

	function handleSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		const trimmed = value.trim();
		if (!trimmed) {
			return;
		}
		onSend(trimmed);
		setValue("");
	}

	return (
		// `shrink-0` (D13): the composer stays pinned at the bottom of the
		// `h-dvh` column instead of a tall transcript squeezing it out.
		<form onSubmit={handleSubmit} className="flex shrink-0 gap-2 border-t p-3">
			<Input
				ref={inputRef}
				data-testid="composer-input"
				value={value}
				onChange={(event) => setValue(event.target.value)}
				placeholder={t("chat.placeholder")}
				disabled={disabled}
			/>
			<Button
				type="submit"
				data-testid="composer-send"
				disabled={disabled || value.trim().length === 0}
			>
				{t("chat.send")}
			</Button>
		</form>
	);
}

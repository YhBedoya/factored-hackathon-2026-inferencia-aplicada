import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { LoginForm } from "@/components/auth/LoginForm";
import { ME_QUERY_KEY } from "@/components/layout/useLogout";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/lib/i18n";

type LoginDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

/**
 * The customer login, as a pop-up over the landing (there is no `/login`
 * page). The landing opens it from `?login=true`, so links, the `/home` and
 * `/chat` guards and `lib/api.ts`'s 401 fallback all reach it by URL. A
 * successful login lands on `/home`, same as the old page did.
 */
export function LoginDialog({ open, onOpenChange }: LoginDialogProps) {
	const { t } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();

	async function handleSuccess() {
		await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
		await navigate({ to: "/home" });
	}

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent
				data-testid="login-dialog"
				className="sm:max-w-sm"
				aria-describedby={undefined}
			>
				<DialogHeader>
					<DialogTitle>{t("login.title")}</DialogTitle>
				</DialogHeader>
				<LoginForm onSuccess={handleSuccess} />
			</DialogContent>
		</Dialog>
	);
}

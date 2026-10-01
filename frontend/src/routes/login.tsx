import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { LoginForm } from "@/components/auth/LoginForm";
import { ME_QUERY_KEY } from "@/components/layout/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/login")({
	component: LoginPage,
});

function LoginPage() {
	const { t } = useI18n();
	const navigate = useNavigate();
	const queryClient = useQueryClient();

	async function handleSuccess() {
		await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
		await navigate({ to: "/home" });
	}

	return (
		<div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 py-16">
			<Card>
				<CardHeader>
					<CardTitle>{t("login.title")}</CardTitle>
				</CardHeader>
				<CardContent>
					<LoginForm onSuccess={handleSuccess} />
				</CardContent>
			</Card>
		</div>
	);
}

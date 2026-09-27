# B7: sandbox and support commands for D1-B. `make setup`/`data`/`up`/`check`/
# `eval` (CLAUDE.md's planned commands) are A2's targets, not this card's; add
# them here rather than duplicating the file once A2 lands.

.PHONY: chat-sandbox chat-ui nlu-smoke graph-diagram

chat-sandbox:
	@test -n "$(CUSTOMER)" || (echo "Usage: make chat-sandbox CUSTOMER=<customer_id>" && exit 1)
	cd backend && uv run python -m app.domains.conversation.sandbox --customer "$(CUSTOMER)"

chat-ui:
	@echo "Sandbox UI: http://localhost:8501"
	cd backend && uv run streamlit run scripts/sandbox_ui.py

nlu-smoke:
	cd backend && uv run python scripts/nlu_smoke.py

graph-diagram:
	cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd

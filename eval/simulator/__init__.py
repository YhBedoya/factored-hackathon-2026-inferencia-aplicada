"""Goal-driven customer simulator package (B1, D6-B): `run_case_simulated`
plays one `Case` by asking the `simulate` LLM step for the customer's next
action, instead of following a fixed turn script past turn 1. Re-exported
here so `eval.harness.__main__`'s `--driver simulator` branch does
`from eval.simulator import run_case_simulated` (D15).
"""

from eval.simulator.simulator import SimAction, run_case_simulated

__all__ = ["SimAction", "run_case_simulated"]

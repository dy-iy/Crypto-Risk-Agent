import json
from typing import Dict

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.prompt.tx_judge_prompt import PATCH_JUDGE_UP, PATCH_JUDGE_SP
from app.attackpilot.utils.verification import adjudicate_patch_verification


class JudgeAgent(AgentBase):
    def __init__(self, dapp_name, name="Transaction Judge", metrics_collector=None, log_callback=None):
        super(JudgeAgent, self).__init__(name, PATCH_JUDGE_SP, unique_id=dapp_name, max_turns=2,log_callback=log_callback)
        self.metrics_collector = metrics_collector
        self.unique_id = dapp_name

    async def handle(self, judge_data: Dict) -> Dict:
        prompt = PATCH_JUDGE_UP.format(
            current_hypothesis=json.dumps(judge_data["current_hypothesis"], ensure_ascii=False),
            replay_logs=json.dumps(judge_data["replay_logs"], ensure_ascii=False),
            patches=judge_data["patches"],
            real_balance_change=json.dumps(judge_data["real_balance_change"], ensure_ascii=False)
        )
        for attempt in range(2):
            self._check_cancelled()
            result = await self.query(prompt, _format="json")
            result = result if isinstance(result, dict) else {"verdict": "UNVERIFIED"}
            state = adjudicate_patch_verification(result, judge_data["replay_logs"], judge_data["patches"])
            result["verification"] = state
            result["evidence_review_attempts"] = attempt + 1
            # Declared sequential verification is decided by the coordinator's
            # execution checks. Preserve this model interpretation without
            # querying again to obtain a different textual verdict.
            if state.get("evidence_version") == 2 or state.get("next_action") != "review_same_evidence":
                break
            if attempt:
                state.update(terminal=True, retryable=False, next_action="inspect_judge_evidence")
                break
            # Reconsider the same execution once. A model disagreement never
            # justifies rerunning a paid simulation or fabricating a verdict.
            review = (
                "The coordinator has completed its deterministic checks for the supplied trigger inputs. "
                "Review these check references and your previous interpretation against the same evidence. "
                "Respect the reported scope and deterministic dimensions. The declared_attack_chain scope "
                "requires passing sequence_replay, attack_interception, and security_properties dimensions. "
                "When no normal cases are declared, normal_regression=not_run does not block that attack-scoped "
                "verdict and does not establish normal-function coverage. The declared_attack_chain_and_normal_cases "
                "scope additionally requires recorded normal cases with passing business assertions. "
                "A security result must preserve every declared invariant and eliminate at least one observed "
                "original violation. Profit valuation is supplementary. "
                "Keep UNVERIFIED if any required dimension remains unsupported.\n"
                + json.dumps({"coordinator_verification": state, "previous_interpretation": {
                    key: result.get(key) for key in ('verdict', 'reason', 'evidence_refs', 'target_checks')
                }}, ensure_ascii=False)
            )
            prompt = review + '\n\n' + PATCH_JUDGE_UP.format(
                current_hypothesis=json.dumps(judge_data["current_hypothesis"], ensure_ascii=False),
                replay_logs=json.dumps(judge_data["replay_logs"], ensure_ascii=False),
                patches=judge_data["patches"],
                real_balance_change=json.dumps(judge_data["real_balance_change"], ensure_ascii=False),
            )
            # The review prompt already contains the original evidence and
            # relevant earlier interpretation; avoid a second full copy in
            # chat history exceeding the model's context window.
            self.init_system_prompt(PATCH_JUDGE_SP)
        # Models interpret execution evidence; unavailable measurements remain unknown.
        details = result.get("analysis_details")
        details = dict(details) if isinstance(details, dict) else {}
        details["attacker_profit_usd"] = result["verification"]["dimensions"]["profit"]["usd"]
        result["analysis_details"] = details

        if self.metrics_collector and isinstance(result, dict):
            state = result["verification"]
            if state.get("evidence_version") == 2:
                verdict = ("VERIFIED" if state.get("status") == "verified"
                           and state.get("evidence_validated") is True else "UNVERIFIED")
                feedback = str(state.get("reason", ""))
            else:
                verdict = result.get("verdict") if state.get("evidence_validated") else "UNVERIFIED"
                feedback = str(result.get("reason", "")) + " " + str(result.get("feedback_to_agent", ""))
            if verdict:
                self.metrics_collector.record_judge_result(
                    case_name=self.unique_id,
                    verdict=verdict,
                    reason=feedback
                )
        
        return result

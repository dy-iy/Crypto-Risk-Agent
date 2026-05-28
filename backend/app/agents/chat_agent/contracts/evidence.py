from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceContract, ScenarioId, ScenarioHypothesis


SCENARIO_FIELDS: dict[ScenarioId, list[str]] = {
    "S0_GENERAL_UNKNOWN": [
        "article_type",
        "source_type",
        "risk_signal_summary",
        "why_no_specific_scenario",
        "insufficient_evidence_reason",
    ],
    "S1_ATTACK_EXPLOIT": [
        "exploit_occurred",
        "attack_vector",
        "loss_usd",
        "user_fund_affected",
        "attacker_address",
        "mitigation_status",
        "is_security_research_only",
        "is_historical_event",
        "official_confirmation",
    ],
    "S2_EXCHANGE_ABNORMALITY": [
        "withdrawal_suspended",
        "deposit_suspended",
        "trading_halted",
        "withdrawal_delay_only",
        "official_notice",
        "planned_maintenance",
        "recovery_time",
        "fund_safety_statement",
        "already_resolved",
        "affected_assets",
        "affected_exchange",
    ],
    "S3_STABLECOIN_RESERVE": [
        "stablecoin_name",
        "depeg_mentioned",
        "depeg_price",
        "reserve_issue",
        "redemption_suspended",
        "issuer_statement",
        "duration_mentioned",
    ],
    "S4_INFRASTRUCTURE_FAILURE": [
        "network_outage",
        "block_production_stopped",
        "oracle_failure",
        "bridge_paused",
        "rpc_or_node_failure",
        "affected_chain_or_protocol",
        "user_transactions_affected",
        "funds_at_risk",
        "already_resolved",
    ],
    "S5_REGULATORY_ENFORCEMENT": [
        "regulator",
        "target_entity",
        "enforcement_action",
        "penalty_or_freeze",
        "lawsuit_or_charge",
        "jurisdiction",
        "legal_status",
        "is_policy_discussion_only",
        "is_positive_regulatory_clarity",
    ],
    "S6_MARKET_LIQUIDATION": [
        "price_drop_pct",
        "time_window",
        "liquidation_amount_usd",
        "market_scope",
        "is_major_asset",
        "is_normal_market_commentary",
        "is_forecast_only",
        "liquidity_stress_mentioned",
    ],
    "S7_FRAUD_GOVERNANCE": [
        "phishing_site",
        "fake_airdrop",
        "impersonation",
        "fake_token",
        "wallet_connection_lure",
        "user_loss_confirmed",
        "fraud_claim",
        "rug_pull_or_exit",
        "team_missing",
        "funds_removed",
        "official_response",
        "is_ordinary_team_change",
    ],
    "S8_WHALE_ONCHAIN_FLOW": [
        "large_transfer",
        "to_exchange",
        "from_exchange",
        "amount_usd",
        "token_or_asset",
        "internal_transfer",
        "wallet_address",
        "sell_pressure_indicated",
    ],
}


def build_contracts(hypotheses: list[ScenarioHypothesis]) -> list[EvidenceContract]:
    return [
        EvidenceContract(
            scenario=hypothesis.scenario,
            fields=SCENARIO_FIELDS[hypothesis.scenario],
        )
        for hypothesis in hypotheses
    ]

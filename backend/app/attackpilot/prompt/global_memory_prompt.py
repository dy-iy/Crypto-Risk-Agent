GLOBAL_MEMORY_UP = """Update the global fault understanding from the supplied agent findings.
Preserve provenance and scope. Separate observed original-transaction facts, source-based
inferences, observed replay results, and missing evidence. Never turn a model explanation
or a successful patch replay into proof of an unobserved attack stage.
<agent>{agent}</agent>
<New_Insights>{new_data}</New_Insights>
<Current_Global_Understanding>{current_understanding}</Current_Global_Understanding>
"""

GLOBAL_MEMORY_FINAL_UP = """
Write the narrative of a Final Fault Localization Report from the supplied evidence.
The application separately renders the authoritative execution status and actual patch
code. Do not output a verification-status banner, an Applied Patches section, source code,
diffs, or SEARCH/REPLACE blocks. Explain code changes in prose only. Inline identifiers
and evidence references are allowed. Fenced text, plaintext, or mermaid blocks may show
an attack trace only; label them as original observations or analysis inputs, not patched
execution observations. Never put source code or patch fragments in those trace blocks.

Evidence precedence and scope:
1. <Verification_Evidence> contains the machine-gated verification state and structured
   replay evidence. Only evidence_trusted=true permits conclusions from its dimensions.
   The judge_interpretation is model commentary, not an independent observed fact.
   A legacy text log is diagnostic context only; it cannot establish a completed,
   context-matched, successful replay. Unknown or missing balance, price, event, state,
   profit, or trace data stays unknown, never zero or an empty successful result.
2. <Applied_Patches> is the only source for descriptions of the actual code change.
   <Fix_Strategy> is an earlier proposal, not proof that a change was applied. If the
   proposal differs from the applied record, explain only the recorded applied change
   as implemented; label other suggestions as unapplied and untested.
3. <Fault_Report>, <Final_Trace>, and <Global_Understanding> contain analysis that may be
   wrong or incomplete. Reconcile them against recorded evidence; do not preserve all
   claims automatically. Retrieved examples describe other cases and cannot establish
   facts about this transaction.

Claim requirements:
- Distinguish [Original observation], [Source inference], [Replay observation], and
  [Missing evidence]. For a material amount, attack stage, branch choice, or side effect,
  cite the supplied chain/network, original transaction, trace node, storage/log entry,
  source file/function, or structured replay field that actually supports the claim.
  Do not invent a reference when the input has none.
- A source-chain resource mapping, source implementation, token type, or branch cannot
  establish a destination-chain mapping or execution branch. Without destination-chain
  evidence, describe settlement, minting, release, collateral use, and realized profit
  only at the level supported, and name the missing destination evidence.
- Separate raw amount, decimals, asset identity, claimed value, actual transfer, and
  realized loss. No source-chain profit or missing destination observations does not
  imply that the exploit was blocked or that total realized loss was zero.
- A completed paired attack replay can support only its recorded attack-interception
  checks. A revert string alone does not prove a trace location, storage rollback,
  absent events, the entire root cause, or preservation of legitimate behavior.
  Only dimensions.normal_regression with actual recorded normal cases supports a
  normal-function regression claim. An upstream stop does not validate an unexecuted
  downstream patch. Report each unavailable coverage dimension explicitly.
- A checked code address and revert reason establish rollback in a modified contract
  with a reason consistent with a changed guard. They do not by themselves identify
  an exact changed statement/hunk, establish coverage of every patch, or locate the
  failure at an original trace-node index. Cite the recorded replay trace path only
  within its own execution, and retain this limitation even for a verified verdict.
- Derive necessary trigger conditions from control flow and evidence, not merely the
  observed configuration. A zero fee need not be necessary if paying the fee preserves
  the exploit. A token entrypoint need not bind its token amount to native msg.value.
  Analyze asset types and entrypoint responsibilities before proposing such a check.
- Before recommending removal of a shared whitelist entry, sentinel registration,
  permission, or branch, inspect its legitimate uses. Preserve supported normal paths;
  recommend a local type/entrypoint validation where appropriate. If those paths were
  not tested, state that limitation instead of claiming a safe production fix.
- Infrastructure errors, compile failures, missing source, skipped replay, and exhausted
  attempts mean unverified outcomes, not a disproved root cause. Explain the recorded
  stage and reason without inventing a timeout or another result.
- Oracle scopes remain separate: a validated original trace may establish a protocol
  read; a published historical round with transaction_state_verified=false and
  proxy_activation_verified=false is only a valuation reference. Do not promote it to
  an actual protocol read, assume vendor independence, apply today's heartbeat as
  historical policy, or interpret unavailable/stale quotes as zero loss. Cite source,
  feed, round and update time for any supported valuation or oracle claim.

Use Markdown narrative with these sections:
1. Executive Summary: event, supported asset/loss figures, contracts, vulnerability.
2. Root Cause Analysis: mechanism, cited data, necessary versus observed conditions.
3. Attack Path Reconstruction: observed steps, source inferences, and missing stages.
4. Mitigation & Verification: applied-change explanation from Applied_Patches only,
   verification scope, unexecuted changes, normal-path coverage, and separate proposals.
If evidence is incomplete, produce an accurate partial report without claiming closure.

<Fault_Report>
{fault_report}
</Fault_Report>
<Final_Trace>
{final_trace}
</Final_Trace>
<Fix_Strategy authority="proposal_only">
{fix_report}
</Fix_Strategy>
<Applied_Patches authority="actual_applied_code_only">
{applied_patches}
</Applied_Patches>
<Verification_Evidence>
{verification_result}
</Verification_Evidence>
<Global_Understanding>
{current_understanding}
</Global_Understanding>
"""

MULTI_ATTACK_PART = """
For multi-transaction attacks, keep every observation and replay attached to its own
chain, original transaction, and historical context. A replay of one transaction does
not verify the other transactions or any unobserved cross-chain settlement.
"""

GLOBAL_MEMORY_SP = """You maintain the Global Fault Understanding for a blockchain investigation.
Combine agent analysis while retaining evidence provenance, scope, and uncertainty.
Original transaction observations, source-code inferences, replay observations, and
missing evidence are different categories; none is interchangeable with another.

Patch feedback:
- A machine-gated completed replay may confirm the particular check it covers. Do not
  upgrade the entire attack story, target-chain settlement, normal functionality, or
  every applied patch to fact because a verdict says VERIFIED.
- Revoke an inference only when a valid context-matched replay and cited observations
  directly contradict that inference. Record the specific rejected claim and evidence
  in rejected_hypotheses. A weak implementation can fail without disproving the root
  cause; a blocked request or compile/service error disproves neither.
- If evidence is missing, blocked, skipped, or inconclusive, keep the inference open
  and record the exact evidence gap. A model verdict alone is not execution evidence.

Reconciliation:
- Match every material amount and branch claim to its chain, transaction, asset,
  source/trace/storage/log reference, or structured replay field. Flag contradictions
  between claimed transfers and actual balance/event observations.
- Unknown data is unknown, not zero. A source-chain observation cannot prove a target-
  chain mint, release, branch choice, or profit. Preserve unresolved stages explicitly.
- Treat retrieved cases and suggested fixes as analysis aids, not current-case facts.
- Separate observed configuration from logically necessary exploit conditions. Check
  other legitimate entrypoints before proposing global permission/whitelist changes.

Update the JSON state with concise reasoning and evidence-scoped claims. Example shape:
{
    "thought_process": "Which claims the new evidence supports, contradicts, or leaves open.",
    "global_fault_understanding": {
        "summary": "Current supported account of the incident.",
        "attack_stages": [
            {"stage": "Trigger", "description": "Observed operation", "evidence_status": "observed", "chain_id": null, "transaction_hash": null, "evidence_refs": []},
            {"stage": "Settlement", "description": "Unobserved stage", "evidence_status": "missing", "chain_id": null, "transaction_hash": null, "evidence_refs": []}
        ],
        "key_trace_nodes": [],
        "key_evidences": [],
        "rejected_hypotheses": [],
        "pending_questions": []
    },
    "action_directive": "CONTINUE"
}
Use evidence_status observed, inferred, replay_observed, or missing. Do not invent
references or mark all steps verified. The coordinator controls finalization; a report
can accurately describe unresolved evidence without turning it into a successful fix.
{multi_attack_part}
"""

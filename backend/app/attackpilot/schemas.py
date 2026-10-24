from typing import Literal
from pydantic import BaseModel, Field, field_validator

MODULES = ("attack_detection", "fault_localization", "rag_retrieval", "patch_generation", "patch_verification")

def normalize_modules(modules: list[str] | None) -> list[str]:
    selected = set(MODULES if not modules else modules)
    if selected - set(MODULES):
        raise ValueError("未知分析模块")
    if "patch_verification" in selected:
        selected.add("patch_generation")
    if "patch_generation" in selected:
        selected.add("fault_localization")
    if "fault_localization" in selected:
        selected.add("rag_retrieval")
    selected.add("attack_detection")
    return [module for module in MODULES if module in selected]

class TransactionInput(BaseModel):
    tx_hash: str = ""
    tx_hashes: list[str] = Field(default_factory=list, max_length=50)
    chain: Literal["ethereum", "bnbchain"] = "ethereum"
    modules: list[str] = Field(default_factory=list)
    verification_plan: dict | None = None

    @field_validator("verification_plan")
    @classmethod
    def plan_valid(cls, value):
        return normalize_input_verification_plan(value)

    @field_validator("modules")
    @classmethod
    def modules_valid(cls, value: list[str]) -> list[str]:
        return normalize_modules(value)

class CaseTaskInput(BaseModel):
    dapp_name: str = Field(min_length=1, max_length=255)
    modules: list[str] = Field(default_factory=list)
    verification_plan: dict | None = None

    @field_validator("verification_plan")
    @classmethod
    def plan_valid(cls, value):
        return normalize_input_verification_plan(value)

    @field_validator("dapp_name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入案例名称")
        return value

    @field_validator("modules")
    @classmethod
    def modules_valid(cls, value: list[str]) -> list[str]:
        return normalize_modules(value)


def normalize_input_verification_plan(value, *, network_id=None, transaction_hashes=None):
    """Validate submitted rules without granting an input investigation authority."""
    from app.attackpilot.utils.security_checks import validate_verification_plan
    plan = validate_verification_plan(value, network_id=network_id)
    if plan is None:
        return None
    if plan['authority']['kind'] != 'user_declared':
        raise ValueError('提交的验证计划必须声明为 user_declared')
    if transaction_hashes is not None and set(plan['attack_transaction_hashes']) != {
            tx.lower() for tx in transaction_hashes}:
        raise ValueError('验证计划须覆盖本次提交的全部攻击序列交易')
    return plan

class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def query_valid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入检索关键词")
        return value

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

    @field_validator("modules")
    @classmethod
    def modules_valid(cls, value: list[str]) -> list[str]:
        return normalize_modules(value)

class CaseTaskInput(BaseModel):
    dapp_name: str = Field(min_length=1, max_length=255)
    modules: list[str] = Field(default_factory=list)

class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)

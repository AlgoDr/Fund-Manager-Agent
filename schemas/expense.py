from typing import Literal
from pydantic import BaseModel, Field

Category = Literal[
    "Food", "Groceries", "Transport", "Shopping", "Utilities",
    "Entertainment", "Health", "Travel", "Education", "Other"
]

class ExtractedExpense(BaseModel):
    amount_phrase: str | None = None
    currency: str | None = None
    category: Category | None = None
    merchant: str | None = None
    date_phrase: str | None = None
    note: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_question: str | None = None

class ExtractionResult(BaseModel):
    expenses: list[ExtractedExpense] = Field(default_factory=list)

class DraftExpense(ExtractedExpense):
    amount_paise: int | None = None
    resolved_date: str | None = None
    clarification_required: bool = False
    clarification_question: str | None = None

class DraftResult(BaseModel):
    transcript: str
    expenses: list[DraftExpense]
    provider_used: str

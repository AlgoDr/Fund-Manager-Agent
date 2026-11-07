"""Evaluation script: compare Groq vs Ollama on 30+ labelled utterances.

Run with:
    uv run python tests/evaluation.py

Requires both GROQ_API_KEY and a running Ollama instance.
Results are printed as a comparison table and saved to evaluation_results.json.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agent_call import _groq, _ollama
from schemas.expense import ExtractionResult

IST = ZoneInfo("Asia/Kolkata")
TODAY = datetime.now(IST).date().isoformat()

LABELLED_UTTERANCES = [
    ("I spent 250 rupees on samosa today", "Food", 25000, "samosa", "simple snack"),
    ("Lunch cost 350 rupees at the canteen", "Food", 35000, "canteen", "lunch meal"),
    ("Dinner was 800 rupees at Taj Hotel last night", "Food", 80000, "Taj Hotel", "dinner with merchant"),
    ("Bought groceries for 1200 rupees", "Groceries", 120000, None, "grocery shopping"),
    ("Spent 45 rupees on tea", "Food", 4500, None, "small amount"),
    ("Breakfast cost 150 rupees", "Food", 15000, None, "breakfast"),
    ("Uber ride was 350 rupees", "Transport", 35000, "Uber", "ride sharing"),
    ("Auto rickshaw fare 80 rupees", "Transport", 8000, None, "auto"),
    ("Petrol pump 2000 rupees", "Transport", 200000, None, "fuel"),
    ("Metro card recharge 500 rupees", "Transport", 50000, None, "metro"),
    ("Bought a shirt for 1500 rupees", "Shopping", 150000, None, "clothing"),
    ("Shoes cost 3000 rupees", "Shopping", 300000, None, "footwear"),
    ("Amazon order 2500 rupees", "Shopping", 250000, "Amazon", "online shopping"),
    ("Electricity bill 1500 rupees", "Utilities", 150000, None, "utility bill"),
    ("Mobile recharge 399 rupees", "Utilities", 39900, None, "phone recharge"),
    ("Internet bill 999 rupees", "Utilities", 99900, None, "broadband"),
    ("Movie tickets 400 rupees", "Entertainment", 40000, None, "cinema"),
    ("Netflix subscription 500 rupees", "Entertainment", 50000, "Netflix", "streaming"),
    ("Doctor consultation 600 rupees", "Health", 60000, None, "medical"),
    ("Medicine 250 rupees", "Health", 25000, None, "pharmacy"),
    ("Train ticket 1200 rupees", "Travel", 120000, None, "rail travel"),
    ("Flight ticket 5000 rupees", "Travel", 500000, None, "air travel"),
    ("Course fee 15000 rupees", "Education", 1500000, None, "course"),
    ("Books 400 rupees", "Education", 40000, None, "study material"),
    (
        "Spent 350 rupees for Uber, 40 rupees for Samosa Pao, and 200 rupees for lunch",
        None, None, None, "three expenses multi"
    ),
    ("I spent some money on food", None, None, None, "missing amount"),
    ("I spent 500 rupees", None, None, None, "missing merchant/category"),
    ("Two thousand rupees for groceries", "Groceries", 200000, None, "number words"),
    ("Fifteen hundred rupees on dinner", "Food", 150000, None, "fifteen hundred"),
    ("Two fifty for tea", "Food", 25000, None, "two fifty"),
    ("Yesterday I spent 100 rupees on milk", "Food", 10000, None, "yesterday"),
    ("Tomorrow will spend 500 on books", "Education", 50000, None, "tomorrow"),
    ("Misc expense 75 rupees", "Other", 7500, None, "other category"),
]


async def evaluate_single(transcript: str, expected: dict) -> dict:
    """Run agent_call on a single transcript and compare with expected."""
    from services.agent_call import agent_call

    result, provider = await agent_call(transcript)
    expenses = result.expenses

    eval_result = {
        "transcript": transcript,
        "provider": provider,
        "num_expenses": len(expenses),
        "expenses": [],
        "json_valid": True,
        "errors": [],
    }

    if not expenses:
        eval_result["errors"].append("No expenses extracted")
        eval_result["json_valid"] = False
        return eval_result

    for i, exp in enumerate(expenses):
        exp_eval = {
            "index": i,
            "amount_phrase": exp.amount_phrase,
            "currency": exp.currency,
            "category": exp.category,
            "merchant": exp.merchant,
            "date_phrase": exp.date_phrase,
            "note": exp.note,
            "clarification_required": exp.clarification_required,
            "clarification_question": exp.clarification_question,
            "category_match": None,
            "merchant_match": None,
        }

        if expected["expected_category"] is not None:
            exp_eval["category_match"] = (
                exp.category == expected["expected_category"]
            )

        if expected["expected_merchant"] is not None:
            exp_eval["merchant_match"] = (
                exp.merchant == expected["expected_merchant"]
            )

        eval_result["expenses"].append(exp_eval)

    return eval_result


async def run_evaluation():
    results = {
        "timestamp": datetime.now(IST).isoformat(),
        "today": TODAY,
        "total_utterances": len(LABELLED_UTTERANCES),
        "providers": {},
    }

    for provider_name in ["groq", "ollama"]:
        print(f"\n{'='*60}")
        print(f"Evaluating with {provider_name.upper()}")
        print(f"{'='*60}")

        provider_results = []
        total = len(LABELLED_UTTERANCES)
        correct_category = 0
        correct_merchant = 0
        total_with_expected_category = 0
        total_with_expected_merchant = 0
        clarification_count = 0

        for idx, (
            transcript,
            exp_cat,
            exp_amt,
            exp_merch,
            notes,
        ) in enumerate(LABELLED_UTTERANCES, 1):
            expected = {
                "expected_category": exp_cat,
                "expected_amount_paise": exp_amt,
                "expected_merchant": exp_merch,
            }

            try:
                if provider_name == "groq":
                    raw = await _groq(transcript)
                    provider = "groq"
                else:
                    raw = await _ollama(transcript)
                    provider = "ollama"

                result = ExtractionResult.model_validate(raw)

                eval_entry = {
                    "transcript": transcript,
                    "provider": provider,
                    "num_expenses": len(result.expenses),
                    "expenses": [],
                }

                for exp in result.expenses:
                    exp_entry = {
                        "category": exp.category,
                        "merchant": exp.merchant,
                        "amount_phrase": exp.amount_phrase,
                        "date_phrase": exp.date_phrase,
                        "clarification_required": exp.clarification_required,
                        "clarification_question": exp.clarification_question,
                    }

                    if exp_cat is not None:
                        total_with_expected_category += 1
                        if exp.category == exp_cat:
                            correct_category += 1
                        exp_entry["category_expected"] = exp_cat
                        exp_entry["category_match"] = exp.category == exp_cat

                    if exp_merch is not None:
                        total_with_expected_merchant += 1
                        if exp.merchant == exp_merch:
                            correct_merchant += 1
                        exp_entry["merchant_expected"] = exp_merch
                        exp_entry["merchant_match"] = exp.merchant == exp_merch

                    if exp.clarification_required:
                        clarification_count += 1

                    eval_entry["expenses"].append(exp_entry)

                provider_results.append(eval_entry)

                status = "✓" if (
                    exp_cat is None or any(
                        e["category"] == exp_cat for e in eval_entry["expenses"]
                    )
                ) else "✗"
                print(f"  [{idx:2d}/{total}] {status} {transcript[:60]}...")

            except Exception as exc:
                print(f"  [{idx:2d}/{total}] ✗ {transcript[:60]}... ERROR: {exc}")
                provider_results.append({
                    "transcript": transcript,
                    "provider": provider_name,
                    "error": str(exc),
                })

        cat_accuracy = (
            correct_category / total_with_expected_category * 100
            if total_with_expected_category > 0 else 0
        )
        merch_accuracy = (
            correct_merchant / total_with_expected_merchant * 100
            if total_with_expected_merchant > 0 else 0
        )

        summary = {
            "total": total,
            "correct_category": correct_category,
            "total_with_expected_category": total_with_expected_category,
            "category_accuracy_pct": round(cat_accuracy, 2),
            "correct_merchant": correct_merchant,
            "total_with_expected_merchant": total_with_expected_merchant,
            "merchant_accuracy_pct": round(merch_accuracy, 2),
            "clarification_required_count": clarification_count,
            "results": provider_results,
        }

        results["providers"][provider_name] = summary

        print(f"\n  {provider_name.upper()} Summary:")
        print(
            f"    Category accuracy: {cat_accuracy:.1f}% "
            f"({correct_category}/{total_with_expected_category})"
        )
        print(
            f"    Merchant accuracy: {merch_accuracy:.1f}% "
            f"({correct_merchant}/{total_with_expected_merchant})"
        )
        print(f"    Clarifications required: {clarification_count}")

    output_file = "evaluation_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_file}")

    print(f"\n{'='*60}")
    print("PROVIDER COMPARISON")
    print(f"{'='*60}")
    groq = results["providers"].get("groq", {})
    ollama = results["providers"].get("ollama", {})
    print(f"{'Metric':<35} {'Groq':<15} {'Ollama':<15}")
    print(f"{'-'*65}")
    print(
        f"{'Category accuracy':<35} "
        f"{groq.get('category_accuracy_pct', 'N/A'):<15} "
        f"{ollama.get('category_accuracy_pct', 'N/A'):<15}"
    )
    print(
        f"{'Merchant accuracy':<35} "
        f"{groq.get('merchant_accuracy_pct', 'N/A'):<15} "
        f"{ollama.get('merchant_accuracy_pct', 'N/A'):<15}"
    )
    print(
        f"{'Clarifications required':<35} "
        f"{groq.get('clarification_required_count', 'N/A'):<15} "
        f"{ollama.get('clarification_required_count', 'N/A'):<15}"
    )


if __name__ == "__main__":
    asyncio.run(run_evaluation())
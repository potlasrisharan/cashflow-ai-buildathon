"""
Groq-powered AI service:
  - categorize_transactions(): Batch-categorize expenses by vendor + amount
  - chat_with_ai(): Finance Q&A assistant
"""
import json
import logging
import re
from typing import Any
from groq import AsyncGroq
from config import settings

client = AsyncGroq(api_key=settings.GROQ_API_KEY)
logger = logging.getLogger(__name__)
GROQ_MODEL = settings.GROQ_MODEL.strip() or "llama-3.1-8b-instant"

CATEGORIES = [
    "Software", "Marketing", "Travel", "Office",
    "Equipment", "Vendors", "Salaries", "Other"
]

DEPARTMENTS = [
    "Engineering", "Sales", "Marketing", "Operations",
    "HR & Admin", "Infrastructure", "Design", "Product"
]

SYSTEM_PROMPT_CATEGORIZE = f"""You are a financial transaction categorizer for an Indian SaaS company.

Given a list of transactions with vendor name and amount, return a JSON array where each item has:
- "category": one of {CATEGORIES}
- "department": one of {DEPARTMENTS}  
- "confidence": float between 0.6 and 1.0

Rules:
- AWS, GCP, Azure, Datadog, GitHub → Software, Engineering
- Google Ads, LinkedIn Ads, Facebook, Meta → Marketing, Marketing
- Airlines, Hotels, Uber, Ola → Travel, Sales
- Zomato, Swiggy, cafeteria → Office, HR & Admin
- Office rent, furniture → Office, Operations
- Unknown or suspicious vendors → Vendors, Operations (confidence 0.5-0.65)

Always return valid JSON array only, no markdown, no explanation.
"""

SYSTEM_PROMPT_CHAT = """You are CashFlow AI, a financial intelligence assistant for an Indian SaaS company.
You have access to their expense data for January 2025:
- Total spend: ₹8,42,300
- 4 anomalies detected (2 critical: unknown vendor ₹50k, duplicate invoice ₹18.4k)  
- Top vendor: AWS Cloud ₹44,000/month
- Subscription waste: 3 unused tools costing ₹18,400/month (Figma, Webflow, Loom)
- Sales department is 20% over budget

Be concise, specific, and number-driven. Always give actionable recommendations.
Format amounts in Indian notation (₹X,XX,XXX).
"""


async def categorize_transactions(rows: list[dict]) -> list[dict[str, Any]]:
    """
    Batch categorize up to 50 transactions using a Groq chat model.
    Returns list of {category, department, confidence} dicts.
    Gracefully falls back to defaults on error.
    """
    if not rows:
        return []

    # Build compact prompt
    items = "\n".join(
        f"{i+1}. vendor={r.get('vendor','?')} amount={r.get('amount',0)}"
        for i, r in enumerate(rows[:50])
    )
    user_msg = f"Categorize these {len(rows)} transactions:\n{items}"

    try:
        resp = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_CATEGORIZE},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()

        # Extract JSON array from response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array in response")

        results = json.loads(match.group())
        # Pad if fewer results returned
        while len(results) < len(rows):
            results.append({"category": "Other", "department": "Operations", "confidence": 0.70})

        return results[:len(rows)]

    except Exception:
        logger.exception("categorize_transactions failed")
        # Safe fallback
        return [
            {"category": "Other", "department": "Operations", "confidence": 0.70}
            for _ in rows
        ]


async def chat_with_ai(message: str, history: list[dict] | None = None) -> str:
    """
    Finance Q&A chat. Accepts user message + optional prior history.
    Returns AI response string.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}]

    if history:
        for h in history[-8:]:  # Keep last 8 turns for context
            messages.append(h)

    messages.append({"role": "user", "content": message})

    try:
        resp = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=512,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("chat_with_ai failed")
        return (
            "I'm having trouble connecting to the AI engine right now. "
            "Please check your Groq API key or try again in a moment."
        )

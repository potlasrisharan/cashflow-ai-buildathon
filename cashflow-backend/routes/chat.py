"""
POST /api/chat    → Finance Q&A powered by Groq LLaMA3
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
from services.ai_service import chat_with_ai

router = APIRouter()


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: Optional[list[dict]] = Field(default=None, max_length=20)


@router.post("")
async def chat(body: ChatMessage):
    history = body.history or []
    cleaned_history = [
        {
            "role": str(item.get("role", "user"))[:16],
            "content": str(item.get("content", ""))[:2000],
        }
        for item in history
        if isinstance(item, dict)
    ]
    reply = await chat_with_ai(body.message, cleaned_history)
    return {
        "reply": reply,
        "role": "assistant",
    }

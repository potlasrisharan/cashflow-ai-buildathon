"""
POST /api/chat    → Finance Q&A powered by Groq LLaMA3
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from services.ai_service import chat_with_ai

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    history: Optional[list[dict]] = None  # [{"role":"user","content":"..."}, ...]


@router.post("")
async def chat(body: ChatMessage):
    reply = await chat_with_ai(body.message, body.history)
    return {
        "reply": reply,
        "role": "assistant",
    }

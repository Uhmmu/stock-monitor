import json

from .schemas import AIStreamEvent


def encode_sse(event: AIStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False, separators=(',', ':'), default=str)}\n\n"


def answer_chunks(answer: str, size: int = 160):
    for start in range(0, len(answer), size):
        yield answer[start:start + size]

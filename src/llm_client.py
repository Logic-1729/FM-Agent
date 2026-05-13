import re
import time
import random
from config import *
from openai import OpenAI, RateLimitError, BadRequestError
from .trace_writer import (
    new_event_id,
    record_llm_exchange,
    utc_now_iso,
)

_openrouter_client = OpenAI(api_key=LLM_OPENROUTER_API_KEY, base_url=LLM_OPENROUTER_API_BASE_URL)

_MAX_RATE_LIMIT_RETRIES = 20


def _retry_create(client, model, messages):
    for attempt in range(_MAX_RATE_LIMIT_RETRIES):
        try:
            response = client.chat.completions.create(model=model, messages=messages)
            return response.choices[0].message.content
        except BadRequestError:
            raise
        except RateLimitError:
            wait = min(2 ** attempt * 5, 300) + random.uniform(1, 10)
            time.sleep(wait)
    raise RuntimeError(f"Rate limited after {_MAX_RATE_LIMIT_RETRIES} retries")


def _extract_tagged(text, start_tag, end_tag):
    pattern = rf"\[{re.escape(start_tag)}\](.*?)\[{re.escape(end_tag)}\]"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None


def _llm_call(client, model, messages, start_tag, end_tag, max_retries=MAX_SPC_ITER,
              trace_dir=None, trace_meta=None):
    trace_meta = trace_meta or {}
    for attempt in range(1, max_retries + 1):
        event_id = new_event_id("llm")
        started = utc_now_iso()
        response = None
        try:
            response = _retry_create(client, model, messages)
        except Exception as exc:
            event = {
                "event_id": event_id,
                "type": "llm_call",
                "stage": "verification",
                "status": "error",
                "start_time": started,
                "end_time": utc_now_iso(),
                "summary": f"LLM call failed: {exc}",
                "metadata": {
                    **trace_meta,
                    "model": model,
                    "attempt": attempt,
                    "start_tag": start_tag,
                    "end_tag": end_tag,
                    "error": str(exc),
                },
            }
            record_llm_exchange(trace_dir, event_id, event, messages)
            raise
        result = _extract_tagged(response, start_tag, end_tag)
        status = "success" if result is not None else "format_error"
        event = {
            "event_id": event_id,
            "type": "llm_call",
            "stage": "verification",
            "status": status,
            "start_time": started,
            "end_time": utc_now_iso(),
            "summary": trace_meta.get("summary", f"LLM call for {start_tag}"),
            "metadata": {
                **trace_meta,
                "model": model,
                "attempt": attempt,
                "start_tag": start_tag,
                "end_tag": end_tag,
                "parsed": result,
            },
        }
        record_llm_exchange(trace_dir, event_id, event, messages, response)
        if result is not None:
            return result
        messages = messages + [
            {"role": "assistant", "content": response},
            {"role": "user", "content": f"Your output format is wrong. Please wrap your answer within [{start_tag}] and [{end_tag}]."}
        ]
    return None

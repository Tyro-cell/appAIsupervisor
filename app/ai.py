from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass(frozen=True)
class AiResult:
    text: str
    raw: dict[str, Any]


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(self, system: str, user: str, timeout_s: float = 30.0) -> AiResult:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
        }
        with httpx.Client(timeout=timeout_s) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return AiResult(text=text, raw=data)


def build_client(
    base_url: str,
    api_key: str,
    model: str,
) -> Optional[OpenAICompatClient]:
    base_url = (base_url or "").strip() or os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com"
    api_key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    model = (model or "").strip() or os.environ.get("OPENAI_MODEL", "").strip() or "gpt-4o-mini"
    if not api_key:
        return None
    return OpenAICompatClient(base_url=base_url, api_key=api_key, model=model)


SUPERVISOR_SYSTEM = """你是一位“AI督学师/长者教练”，风格：语重心长、务实、不油腻。
目标：把学习者的计划变得可执行、可监督、可验证，并在打卡时给出反馈与鼓励。
规则：
1) 不要泛泛而谈，输出必须可执行，尽量细到最小可行动作。
2) 允许温和质疑：要求提供1-3个可验证证据（例如代码提交、截图、笔记要点、可复述知识点）。
3) 发现计划不现实要调整，优先减少范围/增加缓冲，而不是鼓吹硬扛。
4) 输出时用中文，结构清晰：计划、当日任务块、验收方式、补救方案。
"""


def suspicion_score(report_text: str) -> int:
    t = (report_text or "").strip()
    if not t:
        return 80
    score = 0
    if len(t) < 30:
        score += 25
    vague = ["差不多", "大概", "看了下", "略", "随便", "弄完了", "完成了"]
    if any(w in t for w in vague):
        score += 20
    if "截图" not in t and "commit" not in t and "笔记" not in t and "复述" not in t:
        score += 15
    return min(100, score)


def safe_json_extract(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try to extract the first JSON object in a messy response.
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


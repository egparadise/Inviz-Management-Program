# -*- coding: utf-8 -*-
"""통합 LLM 공급자 — Ollama(로컬) / OpenAI(GPT) / Anthropic(Claude) / Google(Gemini)

설정(settings_store)에서 공급자·API키·모델을 읽어 자동 라우팅한다.
모든 AI 기능(챗·AI분류·보고서 AI수정)이 이 모듈의 chat_complete()를 사용한다.
의존성 없이 urllib만 사용(클라우드 호출 시 인터넷 필요).
"""
import json
import urllib.request
import urllib.error


def get_config() -> dict:
    import settings_store as ss
    return {
        "provider": ss.get("ai_provider", "ollama"),  # ollama/openai/anthropic/gemini
        "openai_key": ss.get("ai_openai_key", ""),
        "anthropic_key": ss.get("ai_anthropic_key", ""),
        "gemini_key": ss.get("ai_gemini_key", ""),
        "openai_model": ss.get("ai_openai_model", "gpt-4o-mini"),
        "anthropic_model": ss.get("ai_anthropic_model", "claude-3-5-haiku-latest"),
        "gemini_model": ss.get("ai_gemini_model", "gemini-1.5-flash"),
        "ollama_model": ss.get("ai_default_model", "llama3.1:latest"),
    }


def active_label() -> str:
    cfg = get_config()
    p = cfg["provider"]
    if p == "openai":
        return f"OpenAI · {cfg['openai_model']}"
    if p == "anthropic":
        return f"Anthropic · {cfg['anthropic_model']}"
    if p == "gemini":
        return f"Gemini · {cfg['gemini_model']}"
    return f"Ollama · {cfg['ollama_model']}"


def is_cloud() -> bool:
    return get_config()["provider"] in ("openai", "anthropic", "gemini")


def provider_ready() -> tuple[bool, str]:
    """현재 공급자가 호출 가능한 상태인지 (키/서버) 확인. (ok, 메시지)"""
    cfg = get_config()
    p = cfg["provider"]
    if p == "openai":
        return (bool(cfg["openai_key"]), "OpenAI API 키가 필요합니다." if not cfg["openai_key"] else "")
    if p == "anthropic":
        return (bool(cfg["anthropic_key"]), "Anthropic API 키가 필요합니다." if not cfg["anthropic_key"] else "")
    if p == "gemini":
        return (bool(cfg["gemini_key"]), "Gemini API 키가 필요합니다." if not cfg["gemini_key"] else "")
    # ollama
    try:
        from chat_engine import ollama_available
        return (ollama_available(), "Ollama가 실행되지 않았습니다." if not ollama_available() else "")
    except Exception:
        return (False, "Ollama 확인 실패")


def chat_complete(messages: list[dict], temperature: float = 0.2,
                  json_mode: bool = False, max_tokens: int = 800) -> str:
    """공급자에 맞춰 단발 완성 호출 → 텍스트 반환."""
    cfg = get_config()
    p = cfg["provider"]
    if p == "openai":
        return _openai(messages, cfg, temperature, json_mode, max_tokens)
    if p == "anthropic":
        return _anthropic(messages, cfg, temperature, max_tokens)
    if p == "gemini":
        return _gemini(messages, cfg, temperature, json_mode, max_tokens)
    # 기본: Ollama
    from chat_engine import ollama_chat
    return ollama_chat(messages, model=cfg["ollama_model"], temperature=temperature,
                       json_mode=json_mode, num_predict=max_tokens)


# ====== 자기학습 전용 (오직 오픈소스 Ollama 모델만 사용) ======
# 분석 공급자가 상용 API(GPT/Claude/Gemini)로 설정돼 있어도,
# 자기학습(자가발전·도메인 분류·지식 인덱싱)은 항상 오픈소스 모델로 수행한다.
def learning_model() -> str:
    import settings_store as ss
    return ss.get("learning_model", "llama3.1:latest")


def learning_label() -> str:
    return f"Ollama · {learning_model()} (오픈소스 전용)"


def learning_ready() -> tuple[bool, str]:
    try:
        from chat_engine import ollama_available
        ok = ollama_available()
        return ok, ("" if ok else "Ollama가 실행되지 않았습니다. (학습은 오픈소스 모델만 사용)")
    except Exception as e:
        return False, str(e)


def learning_complete(messages: list[dict], temperature: float = 0.1,
                      json_mode: bool = False, max_tokens: int = 400) -> str:
    """자기학습 전용 완성 호출 — 항상 Ollama(오픈소스). 상용 API 절대 사용 안 함."""
    from chat_engine import ollama_chat
    return ollama_chat(messages, model=learning_model(), temperature=temperature,
                       json_mode=json_mode, num_predict=max_tokens)


def _post_json(url, payload, headers, timeout=90):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ---------- OpenAI (GPT) ----------
def _openai(messages, cfg, temperature, json_mode, max_tokens):
    payload = {
        "model": cfg["openai_model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        data = _post_json("https://api.openai.com/v1/chat/completions", payload,
                          {"Authorization": f"Bearer {cfg['openai_key']}"})
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI 오류 {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")


# ---------- Anthropic (Claude) ----------
def _anthropic(messages, cfg, temperature, max_tokens):
    # system 분리
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    conv = [{"role": ("assistant" if m["role"] == "assistant" else "user"),
             "content": m["content"]} for m in messages if m["role"] != "system"]
    payload = {
        "model": cfg["anthropic_model"],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": conv,
    }
    if system:
        payload["system"] = system
    try:
        data = _post_json("https://api.anthropic.com/v1/messages", payload, {
            "x-api-key": cfg["anthropic_key"],
            "anthropic-version": "2023-06-01",
        })
        parts = data.get("content", [])
        return "".join(b.get("text", "") for b in parts if b.get("type") == "text")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic 오류 {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")


# ---------- Google (Gemini) ----------
def _gemini(messages, cfg, temperature, json_mode, max_tokens):
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue
        contents.append({
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        })
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    payload = {"contents": contents, "generationConfig": gen}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg['gemini_model']}:generateContent?key={cfg['gemini_key']}")
    try:
        data = _post_json(url, payload, {})
        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts", [])
        return "".join(pt.get("text", "") for pt in parts)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini 오류 {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")


# ---------- 4종 헬스체크 (실제 1-토큰 응답 ping) ----------
def ping_all() -> dict:
    """Ollama / OpenAI / Anthropic / Gemini 각각 실제 1-shot 응답을 받아 상태 반환."""
    import time
    cfg = get_config()
    msg = [{"role": "user", "content": "Reply with exactly: pong"}]
    out = {}

    def _wrap(label, fn):
        t0 = time.time()
        try:
            text = fn()
            return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                    "label": label, "response": (text or "").strip()[:120]}
        except Exception as e:
            return {"ok": False, "latency_ms": int((time.time() - t0) * 1000),
                    "label": label, "error": str(e)[:200]}

    # Ollama
    def _o():
        from chat_engine import ollama_chat, ollama_available
        if not ollama_available():
            raise RuntimeError("Ollama 서버에 연결할 수 없습니다 (port 11434)")
        return ollama_chat(msg, model=cfg["ollama_model"], temperature=0, num_predict=20)
    out["ollama"] = _wrap(f"Ollama · {cfg['ollama_model']}", _o)

    # OpenAI
    def _gpt():
        if not cfg["openai_key"]:
            raise RuntimeError("API 키 미등록")
        return _openai(msg, cfg, 0, False, 20)
    out["openai"] = _wrap(f"OpenAI · {cfg['openai_model']}", _gpt)

    # Anthropic
    def _claude():
        if not cfg["anthropic_key"]:
            raise RuntimeError("API 키 미등록")
        return _anthropic(msg, cfg, 0, 20)
    out["anthropic"] = _wrap(f"Anthropic · {cfg['anthropic_model']}", _claude)

    # Gemini
    def _g():
        if not cfg["gemini_key"]:
            raise RuntimeError("API 키 미등록")
        return _gemini(msg, cfg, 0, False, 20)
    out["gemini"] = _wrap(f"Gemini · {cfg['gemini_model']}", _g)

    out["active"] = cfg["provider"]
    return out


# ====== 이미지(영수증) 분석 — Vision API ======
def analyze_receipt_image(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    """영수증 이미지에서 일자·금액·사용처·결제수단·품목을 JSON으로 추출.
    공급자 cfg를 따르되 Vision 미지원이면 fallback (OpenAI gpt-4o-mini → Anthropic Claude).
    """
    import base64, json as _json
    cfg = get_config()
    b64 = base64.b64encode(image_bytes).decode("ascii")

    prompt = (
        "이것은 한국어 영수증 이미지입니다. 다음 항목을 JSON으로 추출하세요. "
        "값을 모르면 null로 두세요. 절대 추측하지 마세요.\n"
        "{\n"
        '  "date": "YYYY-MM-DD",\n'
        '  "amount": 정수(원, 부가세 포함 총액),\n'
        '  "supply": 정수(공급가액, 없으면 null),\n'
        '  "vat": 정수(부가세, 없으면 null),\n'
        '  "place": "사용처/상호 (예: 스타벅스 강남점)",\n'
        '  "payment_method": "법인카드|현금|이체|개인지출|체크카드|기타",\n'
        '  "category_main": "운영비|인건비|판매관리비|R&D|기타",\n'
        '  "category_sub": "회식·접대|사무용품|... 추론",\n'
        '  "items": "주요 품목 요약 (한 줄)",\n'
        '  "confidence": 0.0~1.0\n'
        "}\n"
        "JSON만 출력하세요. 설명, 코드 펜스 금지."
    )

    # OpenAI Vision (gpt-4o-mini)
    if cfg.get("openai_key"):
        try:
            url = f"data:{mime};base64,{b64}"
            payload = {
                "model": cfg["openai_model"],
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 600,
                "response_format": {"type": "json_object"},
            }
            data = _post_json("https://api.openai.com/v1/chat/completions", payload,
                              {"Authorization": f"Bearer {cfg['openai_key']}"})
            text = data["choices"][0]["message"]["content"]
            obj = _json.loads(text)
            obj["_provider"] = f"OpenAI · {cfg['openai_model']}"
            return obj
        except Exception as e:
            err1 = str(e)[:200]
    else:
        err1 = "OpenAI 키 미등록"

    # Anthropic Vision (Claude)
    if cfg.get("anthropic_key"):
        try:
            payload = {
                "model": cfg["anthropic_model"],
                "max_tokens": 600,
                "temperature": 0.1,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64",
                                                     "media_type": mime, "data": b64}},
                        {"type": "text", "text": prompt + "\n응답을 반드시 valid JSON 한 개의 객체로만 시작·종료하세요."},
                    ],
                }],
            }
            data = _post_json("https://api.anthropic.com/v1/messages", payload, {
                "x-api-key": cfg["anthropic_key"],
                "anthropic-version": "2023-06-01",
            })
            parts = data.get("content", [])
            text = "".join(b.get("text", "") for b in parts if b.get("type") == "text")
            # JSON 부분만 추출
            import re as _re
            m = _re.search(r'\{[\s\S]*\}', text)
            obj = _json.loads(m.group(0) if m else text)
            obj["_provider"] = f"Anthropic · {cfg['anthropic_model']}"
            return obj
        except Exception as e:
            err2 = str(e)[:200]
    else:
        err2 = "Anthropic 키 미등록"

    raise RuntimeError(f"Vision 분석 실패 — OpenAI: {err1} / Anthropic: {err2}")

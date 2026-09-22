# -*- coding: utf-8 -*-
"""模型能力自动探测：连通性、首 token 延迟、工具调用支持、PLC 编程测验。

探测结果写入模型条目（ok/latency_ms/tool_support/coding_score），
infer_roles 据此推断「编程主力」与「快速应答」两个角色，供多模型路由使用。
"""
import re
import time

from openai import OpenAI

_PROBE_SYSTEM = "你是西门子 PLC 编程助手。"
_LATENCY_PROMPT = "只回复两个字母：OK"
_TOOL_TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_tag",
        "description": "读取一个 PLC 变量",
        "parameters": {
            "type": "object",
            "properties": {"address": {"type": "string", "description": "变量地址"}},
            "required": ["address"],
        },
    },
}]
_TOOL_PROMPT = "请调用工具读取变量 VW100 的当前值。"
_CODING_PROMPT = (
    "用 S7-200 SMART 的 STL 语句表写一个电机启保停程序：I0.0 启动、I0.1 停止（常闭）、"
    "Q0.0 输出到接触器。直接输出 STL 代码，不要解释。"
)


def _build_client(entry: dict, timeout: int):
    provider = entry.get("provider", "ollama")
    base_url = entry.get("base_url", "").strip()
    api_key = entry.get("api_key", "").strip()
    if provider == "cloud" and not api_key:
        raise RuntimeError(f"模型 {entry.get('model')} 未配置 API Key。")
    if not base_url:
        raise RuntimeError(f"模型 {entry.get('model')} 未配置接口地址。")
    return OpenAI(base_url=base_url, api_key=api_key or "ollama", timeout=timeout)


def _score_stl(text: str) -> int:
    """对启保停 STL 测验输出做规则评分（0~100），用于横向比较模型编程能力。"""
    t = (text or "").strip()
    if not t:
        return 0
    up = t.upper()
    score = 0
    if re.search(r"\bLDN?\b", up):
        score += 30          # 有装载指令
    if "Q0.0" in up:
        score += 25          # 输出到接触器
    if "I0.0" in up:
        score += 15          # 启动按钮
    if "I0.1" in up:
        score += 15          # 停止按钮
    if re.search(r"=\s*Q0\.0", up):
        score += 5           # 线圈输出语法
    if len(t) <= 600:
        score += 10          # 简洁不啰嗦
    return min(score, 100)


def probe_model(entry: dict, timeout: int = 60) -> dict:
    """探测单个模型，返回 {ok, latency_ms, tool_support, coding_score, message}。"""
    result = {
        "ok": False, "latency_ms": 0, "tool_support": False,
        "coding_score": 0, "message": "",
    }
    model = entry.get("model", "")
    try:
        client = _build_client(entry, timeout)
    except RuntimeError as e:
        result["message"] = str(e)
        return result

    # 1) 连通性 + 首 token 延迟（流式）
    t0 = time.perf_counter()
    try:
        stream = client.chat.completions.create(
            model=model,
            stream=True,
            temperature=0,
            messages=[
                {"role": "system", "content": _PROBE_SYSTEM},
                {"role": "user", "content": _LATENCY_PROMPT},
            ],
        )
        first_at = None
        text = ""
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is not None and delta.content:
                if first_at is None:
                    first_at = time.perf_counter()
                text += delta.content
        if first_at is None:
            first_at = time.perf_counter()
        result["ok"] = bool(text.strip())
        result["latency_ms"] = int((first_at - t0) * 1000)
        if not result["ok"]:
            result["message"] = "模型无响应内容"
            return result
    except Exception as e:
        result["message"] = f"连通失败：{e}"
        return result

    # 2) 工具调用支持
    try:
        resp = client.chat.completions.create(
            model=model,
            stream=False,
            temperature=0,
            messages=[{"role": "user", "content": _TOOL_PROMPT}],
            tools=_TOOL_TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message if resp.choices else None
        result["tool_support"] = bool(msg is not None and getattr(msg, "tool_calls", None))
    except Exception:
        result["tool_support"] = False

    # 3) 编程测验（规则评分）
    try:
        resp = client.chat.completions.create(
            model=model,
            stream=False,
            temperature=0,
            messages=[
                {"role": "system", "content": _PROBE_SYSTEM},
                {"role": "user", "content": _CODING_PROMPT},
            ],
        )
        answer = resp.choices[0].message.content if resp.choices else ""
        result["coding_score"] = _score_stl(answer or "")
    except Exception:
        result["coding_score"] = 0

    return result


def infer_roles(models: list):
    """按探测数据推断角色，返回 (编程主力|None, 快速应答|None)。

    编程主力：编程得分最高且达到及格线（30 分）的可用模型（同分取延迟低者）；
    快速应答：首 token 延迟最低的可用模型。
    """
    usable = [m for m in models if m.get("ok") and m.get("model")]
    if not usable:
        return None, None
    coding = max(
        usable,
        key=lambda m: (m.get("coding_score", 0), -m.get("latency_ms", 0)),
    )
    if coding.get("coding_score", 0) < 30:
        coding = None
    fast = min(usable, key=lambda m: m.get("latency_ms", 0))
    return coding, fast

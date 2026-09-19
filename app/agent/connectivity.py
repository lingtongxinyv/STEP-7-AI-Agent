# -*- coding: utf-8 -*-
"""
模型连通性测试。

分级检测并返回结构化结果，供设置对话框/工具栏调用：
    阶段 1  服务连通 + 鉴权      client.models.list()（部分端点不支持则跳过）
    阶段 2  模型是否存在          在模型列表中匹配名称
    阶段 3  极简推理              chat 补全 max_tokens=1，证明模型真正可用

结果 dict：
    ok           bool   最终是否可用（推理成功，或端点限制时连通成功）
    stage        str    失败发生的阶段：service / model / chat
    latency_ms   int    服务响应耗时
    message      str    面向用户的结论
"""
import time

from openai import OpenAI

_SERVICE_TIMEOUT = 12
_CHAT_TIMEOUT = 30


def _endpoint(llm: str) -> tuple:
    if llm["provider"] == "cloud":
        c = llm["cloud"]
        return c["base_url"], c["model"], c.get("api_key", "")
    o = llm["ollama"]
    return o["base_url"], o["model"], "ollama"


def _friendly(e) -> str:
    text = str(e)
    low = text.lower()
    if "connection" in low or "connect" in low:
        return "无法连接服务：请确认地址正确、Ollama 已启动（ollama serve）或网络可达。"
    if "authentication" in low or "api key" in low or "401" in low:
        return "鉴权失败：API Key 不正确或已过期。"
    if "not found" in low and "model" in low:
        return "模型不存在：请检查模型名称，或先 ollama pull 下载。"
    if "timeout" in low or "timed out" in low:
        return "请求超时：服务无响应，请稍后重试或检查网络。"
    if "404" in low:
        return "接口地址返回 404：请检查 base_url 是否包含正确路径（如 /v1）。"
    if "permission" in low or "403" in low:
        return "被拒绝访问（403）：账号无权限或未开通该模型。"
    return f"请求出错：{text}"


def test_connection(llm: dict) -> dict:
    """对当前 llm 配置执行连通性测试（同步调用，应在后台线程执行）。"""
    base_url, model, api_key = _endpoint(llm)
    base_url = (base_url or "").strip()
    model = (model or "").strip()

    if not base_url:
        return {"ok": False, "stage": "service", "latency_ms": 0,
                "message": "接口地址为空，请先填写 base_url。"}
    if not model:
        return {"ok": False, "stage": "model", "latency_ms": 0,
                "message": "模型名称为空，请先填写模型名。"}
    if llm["provider"] == "cloud" and not api_key:
        return {"ok": False, "stage": "service", "latency_ms": 0,
                "message": "未配置 API Key，请先填写后再测试。"}

    client = OpenAI(base_url=base_url, api_key=api_key or " ",
                    timeout=_SERVICE_TIMEOUT)

    # ---- 阶段 1+2：模型列表（连通、鉴权、模型存在性）----
    latency_ms = 0
    model_exists = None
    list_ok = False
    try:
        t0 = time.perf_counter()
        models = client.models.list()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        list_ok = True
        ids = {getattr(m, "id", "") for m in (models.data or [])}
        if ids:
            model_exists = model in ids
            if not model_exists:
                # 容错：部分服务模型名带版本后缀，做包含匹配
                model_exists = any(model in i or i in model for i in ids if i)
    except Exception as e:
        # models.list 不被支持（404/405）时跳过，直接尝试推理
        low = str(e).lower()
        if "404" in low or "405" in low:
            list_ok = False
        else:
            return {"ok": False, "stage": "service", "latency_ms": latency_ms,
                    "message": _friendly(e)}

    if list_ok and model_exists is False:
        return {
            "ok": False,
            "stage": "model",
            "latency_ms": latency_ms,
            "message": (
                f"服务连通正常（{latency_ms} ms），但模型列表中不存在“{model}”。"
                "请检查模型名，或先下载该模型。"
            ),
        }

    # ---- 阶段 3：极简推理，证明模型真正可调用 ----
    chat_client = OpenAI(base_url=base_url, api_key=api_key or " ",
                         timeout=_CHAT_TIMEOUT)
    try:
        t0 = time.perf_counter()
        chat_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0,
        )
        chat_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as e:
        return {"ok": False, "stage": "chat", "latency_ms": latency_ms,
                "message": f"服务已连通，但模型推理失败：{_friendly(e)}"}

    if list_ok:
        message = f"连接成功：服务响应 {latency_ms} ms，模型“{model}”推理正常（{chat_ms} ms）。"
    else:
        message = f"连接成功：模型“{model}”推理正常（{chat_ms} ms）。"
    return {"ok": True, "stage": "done", "latency_ms": latency_ms,
            "message": message}

# -*- coding: utf-8 -*-
"""
Agent 对话核心。

- Ollama 本地模型与云端 OpenAI 兼容接口共用一套 openai SDK，仅配置不同；
- 支持工具调用（function calling）多轮循环；
- 最终回答以流式 token 返回，减少等待感。

事件回调 event(kind, *args)：
    ("status", text)       状态提示
    ("tool", name, args)   开始调用工具
    ("delta", text)        回答增量
    ("error", text)        错误提示
"""
from openai import OpenAI

from .prompts import build_system_prompt
from .tools import TOOL_SPECS, ToolExecutor
from app.programs.templates import program_from_answer

_MAX_TOOL_ROUNDS = 8


class Assistant:
    def __init__(self, config: dict, executor: ToolExecutor):
        self.config = config
        self.executor = executor
        self.transcript = []  # 完整对话记录（含工具消息）

    def update_config(self, config: dict):
        self.config = config

    def reset(self):
        self.transcript = []

    def _build_client(self):
        llm = self.config["llm"]
        if llm["provider"] == "cloud":
            c = llm["cloud"]
            base_url, model, api_key = c["base_url"], c["model"], c.get("api_key", "")
            if not api_key:
                raise RuntimeError("未配置云端 API Key，请在“设置”中填写。")
        else:
            o = llm["ollama"]
            base_url, model, api_key = o["base_url"], o["model"], "ollama"
        return OpenAI(base_url=base_url, api_key=api_key, timeout=llm.get("timeout", 120)), model

    def chat(self, user_text: str, event):
        self.transcript.append({"role": "user", "content": user_text})
        try:
            client, model = self._build_client()
        except RuntimeError as e:
            event("error", str(e))
            return

        system_message = {
            "role": "system",
            "content": build_system_prompt(
                self.config.get("mode", "engineering"),
                self.executor.device_context(),
            ),
        }

        for _round in range(_MAX_TOOL_ROUNDS):
            try:
                stream = client.chat.completions.create(
                    model=model,
                    messages=[system_message] + self.transcript,
                    tools=TOOL_SPECS,
                    tool_choice="auto",
                    temperature=float(self.config["llm"].get("temperature", 0.3)),
                    stream=True,
                )
            except Exception as e:
                event("error", self._friendly_error(e))
                return

            content_parts = []
            # index -> {id, name, arguments}
            tool_parts = {}

            try:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content_parts.append(delta.content)
                        event("delta", delta.content)
                    if getattr(delta, "tool_calls", None):
                        for piece in delta.tool_calls:
                            slot = tool_parts.setdefault(
                                piece.index,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            if piece.id:
                                slot["id"] = piece.id
                            fn = piece.function
                            if fn and fn.name:
                                slot["name"] += fn.name
                            if fn and fn.arguments:
                                slot["arguments"] += fn.arguments
            except Exception as e:
                event("error", self._friendly_error(e))
                return

            # 无工具调用 → 本轮即最终回答
            if not tool_parts:
                answer = "".join(content_parts)
                self.transcript.append({"role": "assistant", "content": answer})
                # 兜底：模型未调用工具而在回答中直接给出程序时，同步到右侧程序面板
                candidate = program_from_answer(answer)
                if candidate is not None:
                    event("program", candidate)
                return

            # 记录带工具调用的 assistant 消息
            tool_calls = []
            for index in sorted(tool_parts):
                part = tool_parts[index]
                tool_calls.append(
                    {
                        "id": part["id"] or f"call_{_round}_{index}",
                        "type": "function",
                        "function": {
                            "name": part["name"],
                            "arguments": part["arguments"] or "{}",
                        },
                    }
                )
            self.transcript.append(
                {"role": "assistant", "content": "".join(content_parts), "tool_calls": tool_calls}
            )

            # 依次执行工具（作业串行，避免并发访问 PLC）
            for call in tool_calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                event("status", f"调用工具：{name} {args}")
                event("tool", name, args)
                try:
                    result = self.executor.dispatch(name, args)
                except Exception as e:  # 任何工具层漏网异常都不允许中断对话
                    result = f"工具执行出错：{e}"
                self.transcript.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )

        event("error", "工具调用轮次过多，已停止。请把需求描述得更具体一些。")

    @staticmethod
    def _friendly_error(e) -> str:
        text = str(e)
        lowered = text.lower()
        if "connection" in lowered or "connect" in lowered:
            return (
                "无法连接模型服务：请确认 Ollama 已启动（命令：ollama serve），"
                "或检查云端 API 地址与网络。"
            )
        if "authentication" in lowered or "api key" in lowered or "401" in lowered:
            return "模型鉴权失败：请检查 API Key 是否正确。"
        if "not found" in lowered and "model" in lowered:
            return "模型不存在：请检查模型名称，或先执行 ollama pull <模型名> 下载。"
        if "timeout" in lowered:
            return "模型响应超时，请稍后重试，或在设置中增大超时时间。"
        return f"模型调用出错：{text}"

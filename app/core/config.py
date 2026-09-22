# -*- coding: utf-8 -*-
"""配置管理：config.json 与 exe / 项目根目录同级，便于便携携带到其他电脑。"""
import json
import os
import sys
from copy import deepcopy

DEFAULT_CONFIG = {
    "llm": {
        # ollama = 本地模型；cloud = OpenAI 兼容云端接口
        "provider": "ollama",
        "ollama": {
            "base_url": "http://localhost:11434/v1",
            "model": "qwen3:8b",
        },
        "cloud": {
            # OpenAI 兼容接口，支持 DeepSeek / 通义千问兼容模式 / 智谱 / 自建端点
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "",
        },
        "temperature": 0.3,
        "timeout": 120,
        # 多模型智能路由：models 非空且 routing=True 时，按任务特征自动分配模型
        # （编程/设计 → 编程主力；简单问答/查询 → 快速应答）
        "routing": False,
        # 模型列表，每条：{provider, base_url, model, api_key,
        #                 ok, latency_ms, tool_support, coding_score}（后四项由探测写入）
        "models": [],
    },
    "plc": {
        "profile": "S7-200 SMART",
        "host": "192.168.2.1",
        "rack": 0,
        "slot": 1,
        "port": 102,
        # 写入门禁：False 时拒绝一切写入，True 时逐条弹窗确认
        "allow_write": False,
        "poll_interval": 1000,
    },
    # learning = 学习模式（引导/提示）；engineering = 工程模式（直接给完整程序）
    "mode": "engineering",
    # MCGS 组态助手默认配置
    "mcgs": {
        "version": "McgsPro",  # McgsPro / 嵌入版 / 通用版
        "protocol": "PPI",     # PPI / Modbus / OPC
    },
    # I/O 地址库：用户预设元件地址（symbol=元件/符号，address=PLC 地址，comment=备注）
    # AI 生成非标程序/组态时优先直接采用库中地址
    "io_library": [],
}

_CLOUD_PRESETS = {
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "通义千问": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "智谱GLM": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
}


def base_dir() -> str:
    """配置与导出文件的基准目录：打包后取 exe 所在目录，开发时取项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def config_file() -> str:
    return os.path.join(base_dir(), "config.json")


def _merge_defaults(user_cfg: dict) -> dict:
    """两层合并：保证新增配置项有默认值，未知顶层键原样保留。"""
    cfg = deepcopy(DEFAULT_CONFIG)
    for key, value in (user_cfg or {}).items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


def _as_int(value, default: int, min_v: int = None, max_v: int = None) -> int:
    """容错转 int（支持 "3"、3.0），越界/非法时用默认值。"""
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return default
    if min_v is not None and v < min_v:
        return min_v
    if max_v is not None and v > max_v:
        return max_v
    return v


def _as_float(value, default: float, min_v: float = None, max_v: float = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if min_v is not None and v < min_v:
        return min_v
    if max_v is not None and v > max_v:
        return max_v
    return v


def _as_str(value, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _migrate_llm_models(user_cfg: dict) -> dict:
    """旧单模型配置自动迁移为 models 列表首条。

    仅当配置文件里从未保存过 llm.models 时执行（保存过空列表也视为已迁移，
    避免用户在 UI 删空模型后被重新填充）。
    """
    llm = user_cfg.get("llm")
    if not isinstance(llm, dict) or "models" in llm:
        return user_cfg
    provider = llm.get("provider") if llm.get("provider") in ("ollama", "cloud") else None
    if provider is None:
        return user_cfg
    src = llm.get(provider)
    if not isinstance(src, dict) or not src.get("model"):
        return user_cfg
    llm["models"] = [{
        "provider": provider,
        "base_url": src.get("base_url", ""),
        "model": src.get("model", ""),
        "api_key": src.get("api_key", "") if isinstance(src.get("api_key"), str) else "",
    }]
    return user_cfg


def normalize_config(cfg: dict) -> dict:
    """规范化配置：手改坏的字段自动纠正为合法值，避免运行期类型错误。"""
    cfg = _merge_defaults(cfg)

    llm = cfg["llm"]
    llm["provider"] = llm.get("provider") if llm.get("provider") in ("ollama", "cloud") else "ollama"
    llm["temperature"] = _as_float(llm.get("temperature"), 0.3, 0.0, 2.0)
    llm["timeout"] = _as_int(llm.get("timeout"), 120, 5, 600)
    if not isinstance(llm.get("ollama"), dict):
        llm["ollama"] = deepcopy(DEFAULT_CONFIG["llm"]["ollama"])
    else:
        o = llm["ollama"]
        o["base_url"] = _as_str(o.get("base_url"), DEFAULT_CONFIG["llm"]["ollama"]["base_url"])
        o["model"] = _as_str(o.get("model"), DEFAULT_CONFIG["llm"]["ollama"]["model"])
    if not isinstance(llm.get("cloud"), dict):
        llm["cloud"] = deepcopy(DEFAULT_CONFIG["llm"]["cloud"])
    else:
        c = llm["cloud"]
        c["base_url"] = _as_str(c.get("base_url"), DEFAULT_CONFIG["llm"]["cloud"]["base_url"])
        c["model"] = _as_str(c.get("model"), DEFAULT_CONFIG["llm"]["cloud"]["model"])
        c["api_key"] = c.get("api_key") if isinstance(c.get("api_key"), str) else ""

    llm["routing"] = bool(llm.get("routing"))
    models = llm.get("models")
    if not isinstance(models, list):
        models = []
    clean_models = []
    for m in models:
        if not isinstance(m, dict):
            continue
        entry = {
            "provider": m.get("provider") if m.get("provider") in ("ollama", "cloud") else "ollama",
            "base_url": _as_str(m.get("base_url"), ""),
            "model": _as_str(m.get("model"), ""),
            "api_key": m.get("api_key") if isinstance(m.get("api_key"), str) else "",
        }
        if not entry["model"]:
            continue
        # 探测结果（可缺失，探测后写回）
        entry["ok"] = bool(m.get("ok"))
        entry["latency_ms"] = _as_int(m.get("latency_ms"), 0, 0)
        entry["tool_support"] = bool(m.get("tool_support"))
        entry["coding_score"] = _as_int(m.get("coding_score"), 0, 0, 100)
        clean_models.append(entry)
    llm["models"] = clean_models

    plc = cfg["plc"]
    plc["profile"] = _as_str(plc.get("profile"), "S7-200 SMART")
    plc["host"] = _as_str(plc.get("host"), "192.168.2.1")
    plc["rack"] = _as_int(plc.get("rack"), 0, 0, 7)
    plc["slot"] = _as_int(plc.get("slot"), 1, 0, 31)
    plc["port"] = _as_int(plc.get("port"), 102, 1, 65535)
    plc["allow_write"] = bool(plc.get("allow_write"))
    plc["poll_interval"] = _as_int(plc.get("poll_interval"), 1000, 200, 60000)

    cfg["mode"] = cfg.get("mode") if cfg.get("mode") in ("learning", "engineering") else "engineering"

    mcgs = cfg["mcgs"]
    mcgs["version"] = (
        mcgs.get("version")
        if mcgs.get("version") in ("McgsPro", "嵌入版", "通用版")
        else "McgsPro"
    )
    mcgs["protocol"] = (
        mcgs.get("protocol")
        if mcgs.get("protocol") in ("PPI", "Modbus", "OPC")
        else "PPI"
    )

    # I/O 地址库：只保留 symbol/address 齐全的合法条目
    lib = cfg.get("io_library")
    if not isinstance(lib, list):
        lib = []
    clean = []
    for entry in lib:
        if not isinstance(entry, dict):
            continue
        sym = str(entry.get("symbol", "")).strip()
        addr = str(entry.get("address", "")).strip().upper()
        comment = str(entry.get("comment", "")).strip()
        if sym and addr:
            clean.append({"symbol": sym, "address": addr, "comment": comment})
    cfg["io_library"] = clean
    return cfg


def load_config() -> dict:
    """读取配置；缺失或损坏时自动生成默认配置，加载后统一规范化。"""
    path = config_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            user_cfg = _migrate_llm_models(user_cfg)
            cfg = normalize_config(user_cfg)
            # 规范化可能修正了坏值，回写一次保持文件一致（失败可忽略）
            save_config(cfg)
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    cfg = deepcopy(DEFAULT_CONFIG)
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> bool:
    """保存配置，返回是否成功；失败时调用方可向用户反馈。"""
    try:
        with open(config_file(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def cloud_presets() -> dict:
    return dict(_CLOUD_PRESETS)

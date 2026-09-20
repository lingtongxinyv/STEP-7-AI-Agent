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


def load_config() -> dict:
    """读取配置；缺失或损坏时自动生成默认配置。"""
    path = config_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg = deepcopy(DEFAULT_CONFIG)
            # 仅做两层合并，保证新增配置项有默认值
            for key, value in user_cfg.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    cfg = deepcopy(DEFAULT_CONFIG)
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(config_file(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def cloud_presets() -> dict:
    return dict(_CLOUD_PRESETS)

# -*- coding: utf-8 -*-
"""McgsScript 片段合成 + 画面 SVG 预览。

脚本片段遵循 McgsScript 语法（类 VBScript/Basic）：
- 无子函数
- 系统函数 ! 前缀，系统变量 $ 前缀
- 对象树 MCGS.用户窗口.窗口名.控件名.属性

按 scada dict 中的变量生成可直接粘贴的脚本骨架。
"""
from .mcgs_knowledge import MCGS_SCRIPT_GRAMMAR


def build_script(scada_ctx):
    """根据 scada 上下文生成 McgsScript 片段。

    返回字符串，可直接粘贴到 MCGS 脚本编辑器。
    """
    variables = scada_ctx.get("variables", [])
    mcgs_version = scada_ctx.get("mcgs_version", "嵌入版")
    name = scada_ctx.get("name", "MCGS组态")

    switch_vars = [v for v in variables if v.get("var_type") == "开关型"]
    number_vars = [v for v in variables if v.get("var_type") == "数值型"]

    lines = []
    lines.append(f"' ====== {name} MCGS 脚本 ======")
    lines.append(f"' 版本：{mcgs_version}  协议：{scada_ctx.get('protocol', '')}")
    lines.append("' 自动派生，需人工校对地址与逻辑")
    lines.append("")

    # 1. 启动脚本
    lines.append("' ----- 启动脚本（用户窗口→窗口属性→启动脚本）-----")
    if number_vars:
        lines.append("' 数值型变量初始化")
        for v in number_vars[:20]:
            init = v.get("init", "0")
            lines.append(f"{v['name']} = {init}")
    lines.append("")

    # 2. 循环脚本
    lines.append("' ----- 循环脚本（用户窗口→窗口属性→循环脚本，周期 1000ms）-----")
    if switch_vars:
        lines.append("' 开关量报警判断示例")
        for v in switch_vars[:10]:
            alm_desc = v.get("comment", v["name"])
            lines.append(f"IF {v['name']} = 1 THEN")
            lines.append(f"    ' {alm_desc} 触发，可在此写报警应答/记录")
            lines.append("    '!Beep()  ' 蜂鸣提示（按需启用）")
            lines.append("ENDIF")
            lines.append("")
    if number_vars:
        lines.append("' 数值量限值报警示例（按需修改上下限）")
        for v in number_vars[:5]:
            nm = v["name"]
            lines.append(f"IF {nm} > 100 THEN")
            lines.append(f"    ' {v.get('comment', nm)} 超上限")
            lines.append("ENDIF")
            lines.append("")
    lines.append("")

    # 3. 退出脚本
    lines.append("' ----- 退出脚本（用户窗口→窗口属性→退出脚本）-----")
    lines.append("' '!SaveDataAll()  ' 退出前全部存盘（按需启用）")
    lines.append("")

    # 4. 按钮响应脚本
    lines.append("' ----- 按钮响应脚本（按钮控件→事件脚本）-----")
    lines.append("' 启动按钮脚本：")
    lines.append("'   MCGS.用户窗口.主画面.控件名.Visible = True")
    lines.append("' 停止按钮脚本：")
    lines.append("'   MCGS.用户窗口.主画面.控件名.Visible = False")
    lines.append("")

    # 5. 报警应答
    lines.append("' ----- 报警应答脚本 -----")
    lines.append("' 变量名.AnswerAlm(-1)  ' 应答所有级别报警")
    lines.append("")

    # 6. 定时存盘
    lines.append("' ----- 定时存盘脚本（运行策略→定时循环策略，周期 60000ms）-----")
    if number_vars:
        lines.append("' 数值型变量定时存盘")
        for v in number_vars[:10]:
            lines.append(f"!SaveData(\"{v['name']}\")")
    lines.append("")

    # 7. 语法参考
    lines.append("' ====== McgsScript 语法参考 ======")
    lines.append(MCGS_SCRIPT_GRAMMAR)

    return "\n".join(lines)


def render_svg_preview(variables, page_name="主画面"):
    """生成画面布局 SVG 示意图（简易矩形+文字布局，作人工组态参考）。"""
    w, h = 800, 600
    svg = []
    svg.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
    svg.append(
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" "
        f"width=\"{w}\" height=\"{h}\" viewBox=\"0 0 {w} {h}\">"
    )

    # 背景
    svg.append(f"<rect width=\"{w}\" height=\"{h}\" fill=\"#f5f5f5\"/>")

    # 标题
    svg.append(
        f"<text x=\"{w//2}\" y=\"40\" font-size=\"24\" "
        f"text-anchor=\"middle\" fill=\"#333\">{page_name}</text>"
    )
    svg.append(f"<line x1=\"50\" y1=\"60\" x2=\"{w-50}\" y2=\"60\" stroke=\"#999\"/>")

    switch_vars = [v for v in variables if v.get("var_type") == "开关型"]
    number_vars = [v for v in variables if v.get("var_type") == "数值型"]

    # 开关量指示灯（红色圆，3 列布局）
    col_x = [120, 320, 520]
    y0 = 90
    for i, v in enumerate(switch_vars[:9]):
        col = i % 3
        row = i // 3
        x = col_x[col]
        y = y0 + row * 100
        label = v.get("comment", v["name"])[:8]
        svg.append(
            f"<circle cx=\"{x}\" cy=\"{y}\" r=\"18\" "
            f"fill=\"#d9534f\" stroke=\"#8b3a37\"/>"
        )
        svg.append(
            f"<text x=\"{x+30}\" y=\"{y+5}\" font-size=\"14\" fill=\"#333\">{label}</text>"
        )

    # 数值量（蓝色矩形显示）
    y1 = y0 + 3 * 100 + 20
    svg.append(
        f"<text x=\"50\" y=\"{y1-10}\" font-size=\"16\" fill=\"#333\">数值显示：</text>"
    )
    for i, v in enumerate(number_vars[:6]):
        col = i % 3
        row = i // 3
        x = col_x[col] - 60
        y = y1 + row * 70
        label = v.get("comment", v["name"])[:8]
        svg.append(
            f"<rect x=\"{x}\" y=\"{y}\" width=\"120\" height=\"40\" "
            f"fill=\"#428bca\" stroke=\"#2a6496\" rx=\"4\"/>"
        )
        svg.append(
            f"<text x=\"{x+8}\" y=\"{y+25}\" font-size=\"14\" fill=\"white\">{label}:?</text>"
        )

    # 按钮区
    by = h - 80
    svg.append(
        f"<rect x=\"50\" y=\"{by}\" width=\"80\" height=\"36\" "
        f"fill=\"#5cb85c\" stroke=\"#4cae4c\" rx=\"4\"/>"
    )
    svg.append(
        f"<text x=\"90\" y=\"{by+23}\" font-size=\"14\" "
        f"text-anchor=\"middle\" fill=\"white\">启动</text>"
    )
    svg.append(
        f"<rect x=\"150\" y=\"{by}\" width=\"80\" height=\"36\" "
        f"fill=\"#d9534f\" stroke=\"#d43f3a\" rx=\"4\"/>"
    )
    svg.append(
        f"<text x=\"190\" y=\"{by+23}\" font-size=\"14\" "
        f"text-anchor=\"middle\" fill=\"white\">停止</text>"
    )

    svg.append("</svg>")
    return "\n".join(svg)

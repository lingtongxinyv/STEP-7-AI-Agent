# -*- coding: utf-8 -*-
"""
经验证的常用 PLC 程序模板库与参数化生成器。

S7-200 SMART 输出 STL（语句表），可直接粘贴进 Micro/WIN SMART 的 STL 编辑器；
S7-1200/1500 输出 SCL。模板中的 {{key}} 由生成器按参数填充。
"""
import re
from dataclasses import dataclass, field


@dataclass
class Template:
    key: str
    name: str
    target: str           # 目标设备
    language: str         # STL / SCL
    description: str
    params: list          # [(key, 说明, 默认值)]
    io_table: list        # [(地址, 说明)]
    code: str
    explanation: str
    import_guide: str


_STL_GUIDE = (
    "1. 打开 STEP 7-Micro/WIN SMART，新建项目并选择实际 CPU 型号\n"
    "2. 菜单“视图(View) > STL”切换到语句表编辑器\n"
    "3. 将下方各 NETWORK 复制到主程序 MAIN(OB1) 中\n"
    "4. 菜单“编辑(Edit) > 编译(Compile)”，确认零错误零警告\n"
    "5. 用“状态图表”先验证 I/Q/M 逻辑，确认无误后再考虑下载真机\n"
    "6. 真机下载前必须人工复核安全逻辑，首次试运行点动确认"
)

_SCL_GUIDE = (
    "1. TIA Portal 打开项目，添加新 FB/FC 并选择语言 SCL\n"
    "2. 在 PLC 变量表中建立代码所用变量\n"
    "3. 粘贴代码后编译，确认零错误\n"
    "4. 先在 PLCSIM 仿真中验证，再下载真机"
)

TEMPLATES = [
    # 1. 启保停
    Template(
        key="motor_latch",
        name="电机启保停控制",
        target="S7-200 SMART",
        language="STL",
        description="最基础的电机启停自锁电路，适用于单台电机/接触器的起停控制",
        params=[
            ("start", "启动按钮地址", "I0.0"),
            ("stop", "停止按钮地址", "I0.1"),
            ("motor", "电机接触器地址", "Q0.0"),
        ],
        io_table=[
            ("I0.0", "启动按钮（常开，自复位）"),
            ("I0.1", "停止按钮（常闭：常态 ON，按下 OFF）"),
            ("Q0.0", "电机接触器线圈"),
        ],
        code=(
            "NETWORK 1 // 电机启保停\n"
            "LD     {{start}}      // 启动按钮\n"
            "O      {{motor}}      // 自锁（自保）触点\n"
            "AN     {{stop}}       // 停止按钮，串联取反\n"
            "=      {{motor}}      // 驱动电机接触器"
        ),
        explanation=(
            "按下启动按钮后 Q0.0 线圈得电，其常开触点闭合维持供电（自锁）；"
            "按下停止按钮回路断开。现场停止按钮及急停通常采用常闭触点，"
            "断线时 PLC 输入点失电即可安全停车，因此程序中用 AN 指令。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 2. 正反转互锁
    Template(
        key="motor_fwd_rev",
        name="电机正反转互锁控制",
        target="S7-200 SMART",
        language="STL",
        description="单台电机正反转，带软件互锁，防止两相电源短路",
        params=[
            ("fwd_start", "正转启动按钮", "I0.0"),
            ("rev_start", "反转启动按钮", "I0.1"),
            ("stop", "停止按钮", "I0.2"),
            ("fwd", "正转接触器", "Q0.0"),
            ("rev", "反转接触器", "Q0.1"),
        ],
        io_table=[
            ("I0.0", "正转启动按钮（常开）"),
            ("I0.1", "反转启动按钮（常开）"),
            ("I0.2", "停止按钮（常闭）"),
            ("Q0.0", "正转接触器 KM1"),
            ("Q0.1", "反转接触器 KM2"),
        ],
        code=(
            "NETWORK 1 // 正转控制\n"
            "LD     {{fwd_start}}\n"
            "O      {{fwd}}\n"
            "AN     {{stop}}\n"
            "AN     {{rev}}        // 软件互锁\n"
            "=      {{fwd}}\n"
            "\n"
            "NETWORK 2 // 反转控制\n"
            "LD     {{rev_start}}\n"
            "O      {{rev}}\n"
            "AN     {{stop}}\n"
            "AN     {{fwd}}        // 软件互锁\n"
            "=      {{rev}}"
        ),
        explanation=(
            "两个线圈各自自锁，并互相串入对方常闭触点：任一方向运行时另一方向无法启动。"
            "软件互锁不能替代硬件互锁——主回路还必须将两个接触器的辅助常闭触点互相串入对方线圈回路，"
            "并建议换向时先按停止、待电机停稳再反向。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 3. 星三角降压启动
    Template(
        key="star_delta",
        name="星三角降压启动",
        target="S7-200 SMART",
        language="STL",
        description="大功率电机星形降压启动、延时后自动切换三角形全压运行",
        params=[
            ("start", "启动按钮", "I0.0"),
            ("stop", "停止按钮", "I0.1"),
            ("main", "主接触器", "Q0.0"),
            ("star", "星形接触器", "Q0.1"),
            ("delta", "三角接触器", "Q0.2"),
            ("timer", "切换定时器", "T37"),
            ("switch_pt", "切换预设值（T37时基100ms，50=5秒）", "50"),
        ],
        io_table=[
            ("I0.0", "启动按钮（常开）"),
            ("I0.1", "停止按钮（常闭）"),
            ("Q0.0", "主接触器 KM"),
            ("Q0.1", "星形接触器 KMY"),
            ("Q0.2", "三角接触器 KMD"),
            ("T37", "星三角切换延时，100ms×50=5s"),
        ],
        code=(
            "NETWORK 1 // 主接触器自锁\n"
            "LD     {{start}}\n"
            "O      {{main}}\n"
            "AN     {{stop}}\n"
            "=      {{main}}\n"
            "\n"
            "NETWORK 2 // 切换计时（T37 为 100ms 时基）\n"
            "LD     {{main}}\n"
            "TON    {{timer}}, {{switch_pt}}\n"
            "\n"
            "NETWORK 3 // 星形接触器\n"
            "LD     {{main}}\n"
            "AN     {{timer}}\n"
            "AN     {{delta}}\n"
            "=      {{star}}\n"
            "\n"
            "NETWORK 4 // 三角接触器\n"
            "LD     {{timer}}\n"
            "AN     {{star}}\n"
            "=      {{delta}}"
        ),
        explanation=(
            "启动瞬间主接触器与星形接触器同时吸合，电机绕组星形接法、以约 1/3 电流降压运行；"
            "5 秒后 T37 动作，星形接触器释放、三角接触器吸合，转入三角形全压运行。"
            "星/三角之间有软件互锁，实际必须再加硬件互锁。重载或大惯量负载可适当增大 PT，"
            "切换电流冲击偏大时可延长启动时间。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 4. 闪烁电路
    Template(
        key="flasher",
        name="可调闪烁电路",
        target="S7-200 SMART",
        language="STL",
        description="两个定时器接力循环，输出占空比可调的方波信号",
        params=[
            ("timer_a", "定时器A", "T37"),
            ("timer_b", "定时器B", "T38"),
            ("on_pt", "亮灯预设值（100ms×10=1秒）", "10"),
            ("off_pt", "灭灯预设值（100ms×10=1秒）", "10"),
            ("lamp", "闪烁输出", "Q0.0"),
        ],
        io_table=[
            ("Q0.0", "闪烁输出（指示灯/蜂鸣器等）"),
            ("T37", "灭→亮计时，100ms 时基"),
            ("T38", "亮→灭计时，100ms 时基"),
        ],
        code=(
            "NETWORK 1 // 灭灯期间计时\n"
            "LDN    {{timer_b}}\n"
            "TON    {{timer_a}}, {{off_pt}}\n"
            "\n"
            "NETWORK 2 // 亮灯期间计时\n"
            "LD     {{timer_a}}\n"
            "TON    {{timer_b}}, {{on_pt}}\n"
            "\n"
            "NETWORK 3 // 闪烁输出\n"
            "LD     {{timer_a}}\n"
            "=      {{lamp}}"
        ),
        explanation=(
            "T37 计时期间 Q0.0 输出 ON，T38 计时期间输出 OFF，二者循环接力产生连续方波。"
            "修改两个 PT 值即可分别调整亮、灭时长（如报警灯短促闪烁可用 5/15）。"
            "若只需固定 1Hz 闪烁，可直接用特殊存储器 SM0.5 的常开触点驱动线圈，无需定时器。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 5. 交通灯
    Template(
        key="traffic_light",
        name="十字路口交通灯",
        target="S7-200 SMART",
        language="STL",
        description="南北/东西两方向红黄绿灯按固定时序循环切换",
        params=[
            ("run", "启动按钮", "I0.0"),
            ("stop", "停止按钮", "I0.1"),
            ("g_ns_pt", "南北绿时长（50=5秒）", "50"),
            ("y_ns_pt", "南北黄时长（20=2秒）", "20"),
            ("g_ew_pt", "东西绿时长（50=5秒）", "50"),
            ("y_ew_pt", "东西黄时长（20=2秒）", "20"),
            ("ns_g", "南北绿灯", "Q0.0"),
            ("ns_y", "南北黄灯", "Q0.1"),
            ("ns_r", "南北红灯", "Q0.2"),
            ("ew_g", "东西绿灯", "Q0.3"),
            ("ew_y", "东西黄灯", "Q0.4"),
            ("ew_r", "东西红灯", "Q0.5"),
        ],
        io_table=[
            ("I0.0", "启动按钮"),
            ("I0.1", "停止按钮"),
            ("Q0.0/Q0.1/Q0.2", "南北方向绿/黄/红灯"),
            ("Q0.3/Q0.4/Q0.5", "东西方向绿/黄/红灯"),
            ("T37~T40", "绿/黄顺序计时，100ms 时基"),
        ],
        code=(
            "NETWORK 1 // 启停自锁\n"
            "LD     {{run}}\n"
            "O      M0.0\n"
            "AN     {{stop}}\n"
            "=      M0.0\n"
            "\n"
            "NETWORK 2 // 南北绿计时\n"
            "LD     M0.0\n"
            "TON    T37, {{g_ns_pt}}\n"
            "\n"
            "NETWORK 3 // 南北黄计时\n"
            "LD     T37\n"
            "TON    T38, {{y_ns_pt}}\n"
            "\n"
            "NETWORK 4 // 东西绿计时\n"
            "LD     T38\n"
            "TON    T39, {{g_ew_pt}}\n"
            "\n"
            "NETWORK 5 // 东西黄计时\n"
            "LD     T39\n"
            "TON    T40, {{y_ew_pt}}\n"
            "\n"
            "NETWORK 6 // 周期到，复位定时器链重新循环\n"
            "LD     T40\n"
            "EU\n"
            "R      T37, 4\n"
            "\n"
            "NETWORK 7 // 南北绿灯\n"
            "LD     M0.0\n"
            "AN     T37\n"
            "=      {{ns_g}}\n"
            "\n"
            "NETWORK 8 // 南北黄灯\n"
            "LD     T37\n"
            "AN     T38\n"
            "=      {{ns_y}}\n"
            "\n"
            "NETWORK 9 // 南北红灯\n"
            "LD     T38\n"
            "AN     T40\n"
            "=      {{ns_r}}\n"
            "\n"
            "NETWORK 10 // 东西绿灯\n"
            "LD     T38\n"
            "AN     T39\n"
            "=      {{ew_g}}\n"
            "\n"
            "NETWORK 11 // 东西黄灯\n"
            "LD     T39\n"
            "AN     T40\n"
            "=      {{ew_y}}\n"
            "\n"
            "NETWORK 12 // 东西红灯\n"
            "LD     M0.0\n"
            "AN     T38\n"
            "=      {{ew_r}}"
        ),
        explanation=(
            "启动后 T37~T40 依次完成南北绿、南北黄、东西绿、东西黄四段计时；"
            "T40 到时通过上升沿指令 EU 配合 R T37,4 将四个定时器复位，下一扫描周期从头循环。"
            "两个方向始终保持一个方向红、另一方向绿/黄，不会出现同时放行动作。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 6. 传送带
    Template(
        key="conveyor",
        name="传送带物料计数与延时停机",
        target="S7-200 SMART",
        language="STL",
        description="光电开关检测物料计件，最后一件离开后延时自动停机",
        params=[
            ("start", "启动按钮", "I0.0"),
            ("stop", "停止按钮（兼计数复位）", "I0.1"),
            ("sensor", "光电开关", "I0.2"),
            ("belt", "传送带电机", "Q0.0"),
            ("counter", "物料计数器", "C1"),
            ("delay_pt", "无料停机延时（50=5秒）", "50"),
            ("target", "计数预设值", "9999"),
        ],
        io_table=[
            ("I0.0", "启动按钮"),
            ("I0.1", "停止按钮（按下同时复位计数器）"),
            ("I0.2", "光电开关（物料遮挡时 ON）"),
            ("Q0.0", "传送带电机接触器"),
            ("C1", "物料件数计数器"),
            ("T37", "无料延时停机，100ms 时基"),
        ],
        code=(
            "NETWORK 1 // 传送带运行\n"
            "LD     {{start}}\n"
            "O      {{belt}}\n"
            "AN     {{stop}}\n"
            "AN     T37\n"
            "=      {{belt}}\n"
            "\n"
            "NETWORK 2 // 无料延时（有料时光电 ON，T37 保持复位）\n"
            "LD     {{belt}}\n"
            "AN     {{sensor}}\n"
            "TON    T37, {{delay_pt}}\n"
            "\n"
            "NETWORK 3 // 物料计数：光电上升沿加一\n"
            "LD     {{sensor}}\n"
            "EU\n"
            "LD     {{stop}}\n"
            "CTU    {{counter}}, {{target}}"
        ),
        explanation=(
            "物料经过光电开关时每遮挡一次产生一个上升沿，CTU 计数加一；"
            "连续进料期间光电信号使 T37 反复复位，传送带持续运行；"
            "最后一件物料离开后光电持续 OFF，5 秒后 T37 动作自动停机，避免空载空转。"
            "按下停止按钮立即停机并复位计数器。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 7. 双皮带连锁
    Template(
        key="dual_belts",
        name="双皮带连锁启停",
        target="S7-200 SMART",
        language="STL",
        description="逆料流方向顺序启动、顺料流方向顺序停止，防止堆料",
        params=[
            ("start", "启动按钮", "I0.0"),
            ("stop", "停止按钮", "I0.1"),
            ("belt2", "下游皮带（2号）", "Q0.1"),
            ("belt1", "上游皮带（1号）", "Q0.0"),
            ("start_pt", "启动间隔（20=2秒）", "20"),
            ("stop_pt", "排空间隔（50=5秒）", "50"),
        ],
        io_table=[
            ("I0.0", "启动按钮"),
            ("I0.1", "停止按钮"),
            ("Q0.1", "下游 2 号皮带（先启后停）"),
            ("Q0.0", "上游 1 号皮带（后启先停）"),
            ("T38", "启动间隔计时"),
            ("T37", "停车排空计时"),
        ],
        code=(
            "NETWORK 1 // 下游皮带先启动\n"
            "LD     {{start}}\n"
            "O      {{belt2}}\n"
            "AN     T37\n"
            "=      {{belt2}}\n"
            "\n"
            "NETWORK 2 // 启动间隔计时\n"
            "LD     {{belt2}}\n"
            "TON    T38, {{start_pt}}\n"
            "\n"
            "NETWORK 3 // 上游皮带延时启动，按停止立即停\n"
            "LD     T38\n"
            "AN     {{stop}}\n"
            "=      {{belt1}}\n"
            "\n"
            "NETWORK 4 // 停车后排空延时\n"
            "LD     {{stop}}\n"
            "TON    T37, {{stop_pt}}"
        ),
        explanation=(
            "按物流安全原则逆料流启动：下游 2 号皮带先启动，2 秒后上游 1 号皮带才启动，避免物料堆压；"
            "停车时上游皮带立即停止送料，下游皮带继续运行 5 秒把余料排空后自动停止。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 8. 往返小车
    Template(
        key="shuttle",
        name="自动往返小车",
        target="S7-200 SMART",
        language="STL",
        description="小车在两个限位开关之间自动往返循环",
        params=[
            ("start", "启动按钮", "I0.0"),
            ("stop", "停止按钮", "I0.1"),
            ("left_limit", "左限位开关", "I0.2"),
            ("right_limit", "右限位开关", "I0.3"),
            ("right_motor", "右行接触器", "Q0.0"),
            ("left_motor", "左行接触器", "Q0.1"),
        ],
        io_table=[
            ("I0.0", "启动按钮"),
            ("I0.1", "停止按钮"),
            ("I0.2", "左限位行程开关"),
            ("I0.3", "右限位行程开关"),
            ("Q0.0", "右行接触器"),
            ("Q0.1", "左行接触器"),
        ],
        code=(
            "NETWORK 1 // 右行控制\n"
            "LD     {{start}}\n"
            "O      {{right_motor}}\n"
            "O      {{left_limit}}\n"
            "AN     {{stop}}\n"
            "AN     {{right_limit}}\n"
            "AN     {{left_motor}}\n"
            "=      {{right_motor}}\n"
            "\n"
            "NETWORK 2 // 左行控制\n"
            "LD     {{right_limit}}\n"
            "O      {{left_motor}}\n"
            "AN     {{stop}}\n"
            "AN     {{left_limit}}\n"
            "AN     {{right_motor}}\n"
            "=      {{left_motor}}"
        ),
        explanation=(
            "启动后小车右行；压下右限位 I0.3 时右行回路断开、左行回路接通开始返回；"
            "压下左限位 I0.2 后再次换向向右，如此循环。两个方向软件互锁，"
            "实际系统应在两端另加极限保护开关（超程时硬切断），并在轨道端点加装机械缓冲。"
        ),
        import_guide=_STL_GUIDE,
    ),
    # 9. SCL 电机（1200/1500）
    Template(
        key="motor_scl",
        name="电机启保停（SCL）",
        target="S7-1200/1500",
        language="SCL",
        description="S7-1200/1500 的 SCL 版电机启停自锁逻辑",
        params=[
            ("start_tag", "启动变量名", "StartButton"),
            ("stop_tag", "停止变量名", "StopButton"),
            ("motor_tag", "电机变量名", "Motor"),
        ],
        io_table=[
            ("StartButton", "启动按钮（Bool，PLC 变量表中映射 %I）"),
            ("StopButton", "停止按钮（Bool）"),
            ("Motor", "电机输出（Bool，映射 %Q）"),
        ],
        code=(
            "// 电机启保停 SCL——变量需先在 PLC 变量表中定义\n"
            'IF "{{stop_tag}}" THEN\n'
            '    "{{motor_tag}}" := FALSE;\n'
            'ELSIF "{{start_tag}}" THEN\n'
            '    "{{motor_tag}}" := TRUE;\n'
            "END_IF;"
        ),
        explanation=(
            "停止条件优先判断：按下停止立即断开；停止未按下且启动按下时置位电机；"
            "其余扫描周期不赋值，输出保持原状态，等效于梯形图自锁。"
            "建议在 OB1 或其循环调用的块中执行本逻辑。"
        ),
        import_guide=_SCL_GUIDE,
    ),
]


# ---------------- 注册表与生成器 ----------------

_REGISTRY = {t.key: t for t in TEMPLATES}

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def get_template(key: str) -> Template:
    if key not in _REGISTRY:
        raise KeyError(f"模板不存在：{key}（可用模板：{', '.join(_REGISTRY)})")
    return _REGISTRY[key]


def list_templates(target: str = None) -> list:
    if target:
        return [t for t in TEMPLATES if t.target == target]
    return list(TEMPLATES)


def default_params(template: Template) -> dict:
    return {key: default for key, _label, default in template.params}


def render(template: Template, params: dict = None) -> dict:
    """按参数填充模板，返回完整程序描述。"""
    values = default_params(template)
    if params:
        for key, value in params.items():
            if key in values and value is not None and str(value) != "":
                values[key] = str(value)

    def _sub(match):
        key = match.group(1)
        return values.get(key, match.group(0))

    code = _PLACEHOLDER.sub(_sub, template.code)
    return {
        "key": template.key,
        "name": template.name,
        "target": template.target,
        "language": template.language,
        "code": code,
        "io_table": list(template.io_table),
        "explanation": template.explanation,
        "import_guide": template.import_guide,
        "params": dict(values),  # 实际参数值，供梯形图地址解析
    }


# ---------------- 从模型内联回答中提取程序（模型未调工具时的兜底） ----------------

_FENCE = re.compile(r"```([A-Za-z]*)\s*\n(.*?)```", re.S)
_HEADING = re.compile(r"^#{1,4}\s*(.+?)\s*#*$", re.M)
_TABLE_ROW = re.compile(r"^\|([^|]+?)\s*\|([^|]+?)\s*\|", re.M)
_ADDR_CELL = re.compile(
    r"^(\s*(I|Q|M|SM|VB|VW|VD|T|C)\d|DB\d|%[IQM]|[A-Za-z_][A-Za-z0-9_]*\s*$)"
)

_CUSTOM_STL_GUIDE = (
    "1. 本程序为模型在对话中直接编写（未经模板验证），导入前必须人工逐条核对指令与地址\n"
    "2. STEP 7-Micro/WIN SMART 新建项目并选择实际 CPU 型号，切换到 STL 视图\n"
    "3. 粘贴代码后编译，确认零错误零警告\n"
    "4. 先用状态图表验证逻辑，确认无误后再考虑下载真机"
)
_CUSTOM_SCL_GUIDE = (
    "1. 本程序为模型在对话中直接编写（未经模板验证），导入前必须人工核对\n"
    "2. TIA Portal 中新建 FB/FC（SCL），在变量表建立所用变量\n"
    "3. 粘贴代码后编译，先 PLCSIM 仿真再下载真机"
)


def program_from_answer(answer: str):
    """从最终回答中解析 STL/SCL 代码块为程序字典；无可用代码块时返回 None。"""
    if not answer:
        return None
    match = None
    for m in _FENCE.finditer(answer):
        tag = m.group(1).lower()
        if tag in ("stl", "awl", "scl"):
            match = m
            break
        if match is None:  # 无语言标记代码块留待内容推断
            match = m
    if match is None:
        return None

    tag = match.group(1).lower()
    code = match.group(2).strip("\n")
    if tag in ("stl", "awl"):
        language = "STL"
    elif tag == "scl":
        language = "SCL"
    else:
        language = "STL" if ("NETWORK" in code or re.search(r"\bTON\b|\bLD\b", code)) else "SCL"

    # 名称：优先标题，其次首个加粗行，再次代码块之前的首个短文本行
    name = "AI 直接编写程序（未经模板验证，请人工核对）"
    h = _HEADING.search(answer)
    if h:
        name = re.sub(r"[*_`]", "", h.group(1)).strip() or name
    else:
        bold = re.search(r"\*\*\s*(.+?)\s*\*\*", answer)
        if bold:
            name = bold.group(1).strip() or name
        else:
            before_code = answer[: match.start()]
            for line in before_code.splitlines():
                text = line.strip().strip("*_`：: ")
                if text and len(text) <= 60 and not text.endswith(("。", "；", "，", "：")):
                    name = text
                    break

    # IO 表：解析两列 Markdown 表格，过滤表头/分隔行
    io_table = []
    for rm in _TABLE_ROW.finditer(answer):
        addr = rm.group(1).strip()
        desc = rm.group(2).strip()
        if not addr or set(addr) <= set("-: "):
            continue
        if "地址" in addr or addr.lower() in ("address", "addr"):
            continue
        if _ADDR_CELL.match(addr) and len(io_table) < 14:
            io_table.append((addr, desc))

    # 工作原理：截取“工作原理”之后的段落
    explanation = (
        "本程序由模型直接在对话中编写，未使用经验证模板，"
        "请人工核对指令、地址与安全逻辑后再使用。"
    )
    principle = re.search(r"(?:工作原理|原理)[：: ]*\n?(.*?)(?:\n\s*#{1,4}|\Z)",
                          answer, re.S)
    if principle:
        text = principle.group(1).strip()
        if text:
            explanation = text[:600]

    return {
        "key": "custom",
        "name": name,
        "target": "S7-200 SMART" if language == "STL" else "S7-1200/1500",
        "language": language,
        "code": code,
        "io_table": io_table,
        "explanation": explanation,
        "import_guide": _CUSTOM_STL_GUIDE if language == "STL" else _CUSTOM_SCL_GUIDE,
        "params": {},
    }


def render_for_chat(program: dict) -> str:
    """把渲染结果组织成可直接在对话中展示的 Markdown 文本。"""
    lines = [
        f"## {program['name']}（{program['target']} · {program['language']}）",
        "",
        "**I/O 分配表：**",
        "",
        "| 地址 | 说明 |",
        "| --- | --- |",
    ]
    for addr, desc in program["io_table"]:
        lines.append(f"| {addr} | {desc} |")
    lines += [
        "",
        "**程序代码：**",
        "",
        f"```{program['language'].lower()}",
        program["code"],
        "```",
        "",
        "**工作原理：**",
        "",
        program["explanation"],
        "",
        "**导入步骤：**",
        "",
        program["import_guide"],
    ]
    return "\n".join(lines)

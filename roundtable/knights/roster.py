"""五骑士的旋钮配置 —— 按进攻姿态分,面对同一道题给出不同的下一步。

差异是**结构性**的,不是文风上的:
- Percival 和 Mordred 拿到同一个登录框:一个试默认口令走正门,一个灌畸形输入找注入。
- Gawain 摆出『这里有个 base64 串』的事实,Lancelot 立刻抓住深钻,Tristan 把它和另一条死路拼起来。
"""

from __future__ import annotations

from .policy import KnightPolicy

# —————————————————————— Gawain:Kali 工具大师 ——————————————————————
GAWAIN = KnightPolicy(
    name="Gawain",
    posture="recon",
    posture_desc="工具师 —— 优先调度和组合现成安全工具、知识库与利用脚本,把工具链价值榨干。",
    search_mode="breadth",
    max_attempts_before_giveup=1,      # 不深挖,扫到就走
    open_new_lines=True,
    read_board_first=False,            # 先蒙头扫,证据自己产
    designer_trust=0.5,
    post_confidence_threshold=0.2,     # 低门槛:事实照单全发(高召回)
    post_partial_findings=True,
    tool_budget_per_cycle=8,
    focus="优先调用 Kali 容器内现成工具、知识库、payload 仓库与利用脚本来验证思路、分析附件、枚举服务、复现实验和提炼可复用命令。你的职责不是空手侦查，而是成为全桌最会用工具的人。",
    tool_style="你是全桌的 Kali 工具大师。每个 cycle 默认至少尝试 1~2 个现成工具、脚本或知识库路径，把关键结果浓缩成 fact/tool_output 供其他骑士复用。优先做可复现、可复制、可交接的工具链验证；拿不准时先实测工具是否真能执行。注意: 不要默认依赖 nmap,先实测工具能否执行; 端口/协议侦察优先用 naabu、ncat/nc、curl、openssl s_client、httpx、whatweb。",
    preferred_tags=["tooling", "kali", "file", "meta", "strings", "enum", "fingerprint"],
)

# —————————————————————— Percival:走正门 ——————————————————————
PERCIVAL = KnightPolicy(
    name="Percival",
    posture="front_door",
    posture_desc="天真直给者 —— 永远先试出题人想让你走的那条最短路。",
    search_mode="breadth",
    max_attempts_before_giveup=2,
    open_new_lines=True,
    read_board_first=False,
    designer_trust=0.9,                # 高度信任出题意图
    post_confidence_threshold=0.5,
    post_partial_findings=False,
    tool_budget_per_cycle=4,
    focus="只问『出题人想让我怎么走』:试最短路、默认口令、显而易见的解码、低垂果实,快速排掉 sanity check。",
    preferred_tags=["easy", "default", "intended", "login", "decode"],
)

# —————————————————————— Mordred:逆向出题人 ——————————————————————
MORDRED = KnightPolicy(
    name="Mordred",
    posture="breaker",
    posture_desc="破坏者 —— 只问出题人没料到什么,专攻非预期解。",
    search_mode="depth",
    max_attempts_before_giveup=3,
    open_new_lines=True,
    read_board_first=False,
    designer_trust=0.1,                # 极度怀疑
    post_confidence_threshold=0.25,    # 低门槛:异常发现也要喊出来
    post_partial_findings=True,
    tool_budget_per_cycle=6,
    focus="故意违反假设:边界值、畸形/超长输入、注入、竞态、整数溢出、协议误用,找非预期解。",
    preferred_tags=["injection", "overflow", "edge", "unintended", "race", "bypass"],
)

# —————————————————————— Lancelot:单线死磕 ——————————————————————
LANCELOT = KnightPolicy(
    name="Lancelot",
    posture="driller",
    posture_desc="钻探者 —— 挑最有希望的一条线,深度优先钻到底或撞死为止。",
    search_mode="depth",
    max_attempts_before_giveup=6,      # 最高耐心
    open_new_lines=True,
    read_board_first=False,
    designer_trust=0.5,
    post_confidence_threshold=0.6,     # 高门槛:钻出结果才发(高精度)
    post_partial_findings=False,
    tool_budget_per_cycle=8,           # 最高工具预算
    focus="禁止读取黑板；只依靠题目本身、Merlin 指令和你自己产出的证据单线深钻到底,产出 artifact 或明确的 dead_end。",
    can_read_board=False,
    preferred_tags=["exploit", "deep", "artifact", "chain"],
)

# —————————————————————— Tristan:侧向缝合 ——————————————————————
TRISTAN = KnightPolicy(
    name="Tristan",
    posture="weaver",
    posture_desc="缝合者 —— 不开新线,只读黑板,把别人的半成品和死路拼成新假设。",
    search_mode="recombine",
    max_attempts_before_giveup=3,
    open_new_lines=False,              # 关键:靠别人喂养
    read_board_first=True,             # 必须先读桌
    designer_trust=0.5,
    post_confidence_threshold=0.55,
    post_partial_findings=False,
    tool_budget_per_cycle=3,
    focus="通读黑板(尤其死路与孤立 fact),寻找『A 的失败 + B 的碎片 = 新路径』的组合,发布重组后的 hypothesis 并引用来源。",
    preferred_tags=["dead_end", "combine", "cross", "insight"],
)

ALL_KNIGHTS: list[KnightPolicy] = [GAWAIN, PERCIVAL, MORDRED, LANCELOT, TRISTAN]

KNIGHTS_BY_NAME: dict[str, KnightPolicy] = {k.name: k for k in ALL_KNIGHTS}

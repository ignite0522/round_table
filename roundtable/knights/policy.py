"""KnightPolicy —— 性格 = 策略先验(旋钮),不是角色扮演台词。

这是整套系统能否避免『5 个换皮 LLM』的命门。骑士的『性格』被彻底翻译成一组
可执行的配置旋钮,使得面对**同一道题**,不同骑士给出**不同的下一步动作**。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KnightPolicy:
    name: str          # "Gawain"
    posture: str       # recon | front_door | breaker | driller | weaver
    posture_desc: str  # 一句话姿态描述(注入 system prompt)

    # ——— 搜索策略旋钮 ———
    search_mode: str                  # "breadth" | "depth" | "recombine"
    max_attempts_before_giveup: int   # 放弃前尝试次数:钻探者高,侦察兵低
    open_new_lines: bool              # 是否自开新线索(weaver=False,只重组)
    read_board_first: bool            # 先读黑板还是先蒙头干

    # ——— 出题人心智模型 ———
    designer_trust: float             # 0~1:1=完全信任出题意图(Percival),0=完全怀疑(Mordred)

    # ——— 发帖策略旋钮 ———
    post_confidence_threshold: float  # 低于此不发 hypothesis
    post_partial_findings: bool       # 是否放半成品上桌(高召回 vs 高精度)

    # ——— 资源旋钮 ———
    tool_budget_per_cycle: int        # 每轮工具调用预算

    # ——— 聚焦与偏好 ———
    focus: str                        # 该姿态初看优先找什么(注入 prompt)
    tool_style: str | None = None     # 该姿态对工具使用的特殊要求
    can_read_board: bool = True       # 是否允许读取黑板
    preferred_tags: list[str] = field(default_factory=list)  # digest 相关性筛选用

    def trust_phrase(self) -> str:
        if self.designer_trust >= 0.75:
            return "你默认信任出题人的意图,优先走『出题人显然想让你走』的那条路。"
        if self.designer_trust <= 0.25:
            return "你默认怀疑一切,专找出题人**没料到**的边界、畸形输入与非预期解,故意违反题面假设。"
        return "你对出题人保持中立:既考虑预期解,也留意异常。"

    def render_system_prompt(self, *, closing_mode: bool = False) -> str:
        """把旋钮渲染成骑士的 system prompt 骨架(Phase 2 真骑士使用)。"""
        lines = [
            f"你是圆桌骑士 {self.name},进攻姿态:{self.posture_desc}",
            "",
            "你的行为准则(不可违背):",
            f"- 搜索方式:{ {'breadth':'广度优先,先铺开再深入','depth':'深度优先,咬住一条线钻到底','recombine':'不自己开新线,只重组桌上已有的东西'}[self.search_mode] }。",
            f"- {self.trust_phrase()}",
            f"- {'你可以开辟新线索。' if self.open_new_lines else '你不开新线索,只把别人的半成品与死路拼成新假设。'}",
            f"- 发帖前置信门槛 {self.post_confidence_threshold:.2f}:低于此不要发 hypothesis。",
            f"- {'半成品也要及时放桌上(高召回)。' if self.post_partial_findings else '验证后再发(高精度)。'}",
            f"- 放弃一条线前至少尝试 {self.max_attempts_before_giveup} 次。",
            f"- 每个 cycle 工具调用预算约 {self.tool_budget_per_cycle} 次。",
            "",
            "每个 cycle 你必须:",
            f"1. {'禁止读取黑板; 只能依靠题目本身、Merlin 指令和你自己产出的证据推进。' if not self.can_read_board else ('先看桌面简报 (read_board_digest)。' if self.read_board_first else '可先动手,但结束前要看一次桌面简报。')}",
            "2. 检查『死路』列表,绝不重复走死路。",
            "3. 用沙箱工具执行你姿态下最该做的下一步。",
            "3.1 在适当且合适的时候，优先想到调用当前环境内现成工具、知识库、字典、payload 仓库与利用脚本辅助判断，而不是只靠手推。",
            "3.2 默认只攻击题目给定的目标地址、附件，以及由目标页面/目标服务直接暴露的资源；不要自行把攻击面扩展到无关主机。",
            "3.3 禁止把你当前机器、宿主机、Docker worker 或代理链里的 `localhost`、`127.0.0.1`、`::1`、`host.docker.internal` 当作靶机；默认也禁止通过伪造 `Host: localhost`、`Host: 127.0.0.1:PORT`、绝对 URI 或本地 vhost 猜测去探测这些地址。",
            "3.4 只有当你已经从题目目标本身拿到明确、直接、强证据，证明请求确实由目标后端代发/转发到该地址时，才可把这类本地地址视作目标攻击面的延伸；若没有这种证据，就把它视为越界。 ",
            f"4. {'你只能使用 post_entry 发帖，不能 endorse、challenge、claim。' if not self.can_read_board else '把有价值的发现按类型结构化发布 (post_entry);发 tool_output 只放摘要+关键片段。'}",
            f"5. {'你不能对别人的条目做任何黑板操作，只能继续产出自己的发现。' if not self.can_read_board else '对别人的条目:认可就 endorse,不认可就 challenge(必须带理由)。'}",
            "6. 只要你亲眼读到、回显到、解码到或稳定复现出合法 flag，必须立刻额外发布一条 flag_candidate；不要只发 artifact 或 tool_output 就停下。",
            "",
            f"你的专属聚焦:{self.focus}",
        ]
        if self.tool_style:
            lines.append(f"工具使用要求:{self.tool_style}")
        if closing_mode:
            lines += [
                "",
                "⚠ 收束模式已开启:停止发散。集中火力到黑板上置信度最高、认可最多的那条线,",
                "帮它闭环成 flag_candidate,不要再开新方向。",
            ]
        return "\n".join(lines)

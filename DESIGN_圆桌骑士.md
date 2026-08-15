# 圆桌骑士 (Round Table) — CTF 多智能体协作系统设计文档

> 一个基于黑板架构的多智能体 CTF 求解系统。一群"姿态各异"的骑士围坐圆桌,面对**同一道题**,各自从不同角度进攻,把重要发现放上桌,彼此自由接纳或质疑,直到 flag 出现,会议散场。

- 状态:设计评审稿 (v0.1)
- 底座:Codex CLI (`codex exec`)
- 执行环境:真沙箱(可跑 shell / pwntools / 逆向 / 网络请求等真实工具)
- 场景约束:单题、全员同目标、限时 4 小时、自由交流

---

## 0. 设计原则(先读这一节)

这套系统所有的取舍都围绕一句话:**在 4 小时里,用多样性换命中率,用结构化换协作效率。**

四条铁律,后面所有设计都服从它们:

1. **黑板是唯一的真相源,不是聊天室。** 骑士之间不直接对话,只通过在黑板上读写**结构化条目**来协作。这是黑板(blackboard)架构的核心,也是避免 N 个 LLM 陷入"互相附和的回音室 + token 爆炸"的关键。

2. **性格 = 策略先验(policy),不是角色扮演台词。** 让骑士说话粗鲁或优雅毫无价值——那只是换皮的同一个 LLM。性格必须落到**可执行的旋钮**上(广度/深度、信任/怀疑出题人、放弃阈值、发帖置信门槛……),使得面对同一道题,不同骑士给出**不同的下一步动作**。这才是多智能体真正值钱的地方。

3. **不按题目类别分工。** 每次只解一道题,全员面对同一目标。按 Web/Pwn/Rev 分只会让人干等。我们**按进攻姿态分**——差异来自"怎么看它、怎么打它",而不是"负责哪一类"。所有骑士共享同一套沙箱工具箱,谁需要谁调用。

4. **真正难的不是"找到就结束",而是"卡住怎么办"。** 终止条件很简单;死路检测、防止全员挤在同一条错路、把卡住的骑士重新指向——这才决定系统在限时里有没有用。这就是 Merlin 存在的理由。

---

## 1. 隐喻 → 架构映射

| 圆桌概念 | 工程组件 | 职责 |
|---|---|---|
| **发牌器 / 总管 Kay** | Orchestrator | 摄入题目(URL、附件、分类提示),放上桌,召集骑士,驱动主循环,监听终止 |
| **圆桌** | 共享黑板 Blackboard | 所有骑士读写的中心。**结构化条目**,不是自由聊天 |
| **骑士 ×5** | 各具"进攻姿态"的 Codex agent | 读桌 → 独立干活(调沙箱工具)→ 把重要发现放桌上 |
| **接纳 / 不接纳** | endorse / challenge 信号 | 骑士对别人的条目投票,形成软共识 |
| **梅林 Merlin** | 元认知 / 调度层 | 不解题,只盯桌子:去重、发现死路、防止全员挤同一条错路、重新指向卡住的骑士 |
| **亚瑟王 Arthur** | Flag 仲裁者 | 验证 flag-candidate → 宣布散会 |

**三个非骑士角色**:Kay 发牌、Merlin 盯桌、Arthur 验旗。它们不参与"进攻",是圆桌的框架。

---

## 2. 五骑士:按进攻姿态分

核心洞察:面对同一道题,凭什么五个人不重样?差异不能来自"负责哪类",只能来自**看它的角度**和**打它的方式**。

| 骑士 | 进攻姿态 | 拿到同一道题,第一步做什么 |
|---|---|---|
| **Gawain(侦察兵)** | 穷举侦察 | 广度优先,把题目/附件/元数据/字符串/端口全过一遍,产出"事实清单",**只摆证据不下结论** |
| **Percival(直给者)** | 走正门 | 只问"出题人想让我怎么走",试最短路、默认口令、低垂果实,快速排掉 sanity check |
| **Mordred(破坏者)** | 逆向出题人 | 只问"出题人没料到什么",专攻边界、畸形输入、非预期解,**故意违反假设** |
| **Lancelot(钻探者)** | 单线死磕 | 从桌上挑当前最有希望的一条线索,深度优先,钻到底或撞死为止 |
| **Tristan(缝合者)** | 侧向重组 | **不自己开新线**,只读黑板,把别人的半成品和死路拼成新假设(靠别人喂养) |

**为什么这五个能不重样**:Percival 和 Mordred 拿到同一个登录框,一个去试默认口令走正门,一个去灌畸形输入找注入;Gawain 摆出"这里有个 base64 串"的事实,Lancelot 立刻抓住深钻,Tristan 则把它和另一条死路拼起来。差异是**结构性**的,不是文风上的。

### 2.1 性格 = 可执行旋钮

每个骑士的"性格"落到一组配置参数上(而非 prompt 里的角色台词)。这是本设计最重要的落地点:

```python
@dataclass
class KnightPolicy:
    name: str                      # "Gawain"
    posture: str                   # "recon" | "front_door" | "breaker" | "driller" | "weaver"

    # ——— 搜索策略旋钮 ———
    search_mode: str               # "breadth" | "depth"
    max_attempts_before_giveup: int   # 放弃前的尝试次数:钻探者高,侦察兵低
    open_new_lines: bool           # 是否自开新线索(Tristan=False,只重组)
    read_board_first: bool         # 先读黑板还是先蒙头干(Tristan=True, Lancelot 偏 False)

    # ——— 出题人心智模型 ———
    designer_trust: float          # 0~1,1=完全信任出题意图(Percival高),0=完全怀疑(Mordred低)

    # ——— 发帖策略旋钮 ———
    post_confidence_threshold: float  # 发帖前的置信门槛:侦察兵/破坏者低(高召回),缝合者/钻探者高(高精度)
    post_partial_findings: bool    # 是否放半成品上桌(Gawain/Mordred=True)

    # ——— 资源旋钮 ———
    tool_budget_per_cycle: int     # 每轮工具调用预算
    focus: str                     # 该姿态初看优先找什么(prompt 注入)
```

五骑士的旋钮取值示例(**决定行为差异的真身**):

| 旋钮 | Gawain 侦察 | Percival 正门 | Mordred 破坏 | Lancelot 钻探 | Tristan 缝合 |
|---|---|---|---|---|---|
| search_mode | breadth | breadth | depth | depth | — (读桌) |
| designer_trust | 0.5 | 0.9 | 0.1 | 0.5 | 0.5 |
| max_attempts_before_giveup | 低 | 低 | 中 | **高** | 中 |
| open_new_lines | True | True | True | True | **False** |
| read_board_first | False | False | False | 偏False | **True** |
| post_confidence_threshold | **低** | 中 | **低** | 高 | 高 |
| post_partial_findings | True | False | True | False | False |

> **数量与并发**:一姿态一骑士,固定 5 人阵容(已确认)。"同姿态池化多开"(例如临时开 3 个钻探者钻不同线索)作为 **Merlin 后期可调度的能力**保留,MVP 不实现。

---

## 3. 黑板协议(系统的心脏)

黑板是所有协作的载体。条目必须结构化,才能让"接纳/不接纳"变成可执行信号。

### 3.1 条目类型

```python
class EntryType(str, Enum):
    FACT        = "fact"          # 客观观察:文件是 ELF、端口开着、有个 base64 串。无需推断
    HYPOTHESIS  = "hypothesis"    # 假设:这可能是 SQL 注入 / 这是 RSA 共模攻击
    ARTIFACT    = "artifact"      # 产出物:反编译代码、解密脚本、中间文件路径、请求响应
    TOOL_OUTPUT = "tool_output"   # 工具原始输出(可折叠,避免污染他人上下文)
    DEAD_END    = "dead_end"      # 死路:这条线试过了,不通,原因是……(极其重要,防重复劳动)
    NEXT_STEP   = "next_step"     # 建议的下一步动作(可被别的骑士认领)
    FLAG_CANDIDATE = "flag_candidate"  # flag 候选,交给 Arthur 验证
```

### 3.2 条目结构

```python
@dataclass
class BoardEntry:
    id: str                       # 唯一 id
    type: EntryType
    author: str                   # "Mordred"
    title: str                    # 一行摘要,供他人快速扫描
    body: str                     # 详情(工具输出折叠存储,默认只给摘要)
    confidence: float             # 0~1,作者的置信度
    refs: list[str]               # 引用的其他条目 id(形成推理图谱)
    tags: list[str]               # 便于检索:["login","sqli","port-8080"]
    endorsements: list[str]       # 认可它的骑士名
    challenges: list[Challenge]   # 质疑(带理由)
    status: str                   # "open" | "claimed" | "resolved" | "refuted"
    claimed_by: str | None        # 被谁认领深挖
    created_at: float
    updated_at: float
```

### 3.3 接纳 / 不接纳 = endorse / challenge

- **endorse(entry_id)**:我认可,愿意在此基础上继续。多个 endorse → 软共识,该条目权重上升,更容易被 Merlin 推给别人。
- **challenge(entry_id, reason)**:我不接纳,附上理由(不是纯反对)。challenge 累积 → 条目转 `refuted`,提醒全员别再走。
- **claim(entry_id)**:我来深挖这条。防止多人无意识撞车(Merlin 会用它做去重)。

> 关键:骑士**不能**直接删除或改写别人的条目,只能 endorse/challenge/claim,或发布引用它的**新条目**。黑板是 append-mostly 的,保留完整推理轨迹,便于回溯和 Merlin 分析。

### 3.4 上下文投喂策略(防 token 爆炸的关键)

骑士每轮**不接收整块黑板**,而是接收一份 **Merlin 生成的桌面简报(digest)**:
- 高价值条目的**标题 + 置信度 + 认可数**(不含完整 body)
- 与该骑士姿态相关的条目(标签匹配 / 姿态偏好)
- 全部 `DEAD_END` 的标题(避免重复劳动,这个必须全给)
- 最新的 `FLAG_CANDIDATE` 状态

在 Codex CLI 落地版中,宿主程序会把 digest 里的高价值条目、相关条目和待认领步骤的少量完整 body 注入本轮 prompt。这把"自由交流"变成**选择性投喂**,而不是全量广播——既保留协作信号,又控住上下文成本。

---

## 4. 三个框架角色

### 4.1 Kay(总管 / 发牌器)= Orchestrator

- 摄入题目:URL、附件路径、题面文字、可选的分类提示
- 初始化黑板:把题目作为根条目 `FACT` 放上桌,拷贝附件进沙箱工作目录
- 召集骑士,驱动主循环(见 §5)
- 监听终止信号(Arthur 确认 flag / 超时 / 全员停滞)
- 记录全程 timeline,产出复盘报告

### 4.2 Merlin(元认知 / 调度)—— 系统能否用的关键

Merlin **不解题**,每隔 N 秒/每轮扫一遍黑板,做四件事:

1. **去重**:发现两个骑士在做同一件事(claim 了相似条目 / 标签高度重叠)→ 让其中一个转向。
2. **死路检测**:
   - 某条线索被多次 challenge、无进展、反复 tool_output 失败 → 标记为 `DEAD_END` 并广播。
   - **全员挤在同一条线**(所有活跃 claim 集中在一个子图)→ 强制分散,给闲置姿态派新方向。
3. **生成桌面简报(digest)**:即 §3.4 的按需投喂内容。
4. **重新指向卡住的骑士**:某骑士连续 K 轮无有效产出 → 给它一个"未被认领的高价值 next_step"或"最久无人碰的 fact"。

Merlin 的判断可以是**规则 + 轻量 LLM 调用**混合:规则处理去重/超时等硬信号,LLM 处理"这几条是不是同一条死路"这种语义判断。

### 4.3 Arthur(Flag 仲裁)

- 监听 `FLAG_CANDIDATE` 条目
- 校验格式(正则匹配赛题 flag 格式,如 `flag\{.*\}`)
- 若题目支持自动提交/校验(有 submit 接口)→ 真提交验证
- 确认通过 → 在黑板发布 `resolved` 根条目,通知 Kay 散会
- 未通过 → 标记该候选 `refuted` 并附原因,骑士继续

---

## 5. 控制循环与并发(基于 Codex CLI)

### 5.1 总体循环

```
Kay 发牌 → 初始化黑板
  │
  ├─ 每个骑士 = 一个独立 async cycle runner(Codex CLI)
  │
  └─ 主循环(直到终止):
        1. Merlin 扫黑板 → 为每个骑士生成 digest
        2. 5 骑士并发执行一个 "cycle":
            读 digest + 可见条目详情 → 调沙箱工具干活 → 返回 JSON 黑板操作
        3. Arthur 检查是否有新 flag_candidate → 验证
        4. 终止判定(见 §6)
```

### 5.2 并发模型

- 5 个骑士是 5 个并发的 `asyncio` 任务,每个 cycle 启动一次 `codex exec` 非交互运行(独立上下文窗口)。
- 骑士**异步**推进,不必步调一致——姿态本就有快慢(Percival 快、Lancelot 慢)。用**事件驱动**而非严格回合:骑士完成一个 cycle 就立刻拿新 digest 继续,不等别人。
- 黑板是共享状态,用 `asyncio.Lock` 保护写操作(append + endorse/challenge/claim)。读走快照。
- Merlin 作为独立协程,定时 tick(如每 10s 或每 M 次黑板写入触发一次)。

> Codex CLI 落地:每个骑士的 prompt 由 KnightPolicy 渲染,宿主程序把 digest 与 Merlin 指令注入本轮 `codex exec`。Codex 在工作目录里使用 shell/文件能力推进题目,最终只返回 JSON 黑板操作:`post_entry / endorse / challenge / claim`,由宿主程序校验并回放到黑板。

### 5.3 骑士单个 cycle 的内部逻辑(system prompt 骨架)

每个骑士的 system prompt 由其 policy 渲染,骨架一致、旋钮不同:

```
你是圆桌骑士 {name},进攻姿态:{posture 描述}。
你的行为准则(不可违背):
- 你的搜索方式:{search_mode}。
- 你对出题人的默认态度:{designer_trust → 信任/怀疑的具体措辞}。
- 你 {open_new_lines? "可以开新线索" : "不开新线索,只重组桌上已有的东西"}。
- 发帖前置信门槛:{post_confidence_threshold}。低于此不要发 hypothesis。
- {post_partial_findings? "半成品也要及时放桌上" : "验证后再发"}。

每个 cycle 你必须:
1. 先看桌面简报(read_board_digest)。{read_board_first 决定是否强制}
2. 检查 DEAD_END 列表,绝不重复走死路。
3. 用沙箱工具执行你姿态下最该做的下一步(工具预算 {tool_budget_per_cycle})。
4. 把有价值的发现按类型结构化发布到黑板。发 tool_output 时只放摘要+关键片段。
5. 对别人的条目,认可就 endorse,不认可就 challenge(必须带理由)。

你的专属聚焦:{focus}
```

---

## 6. 终止与死路检测

### 6.1 终止条件(任一满足即散会)

1. **成功**:Arthur 验证某 `FLAG_CANDIDATE` 通过。
2. **超时**:达到 4 小时硬上限(留 buffer,如 3h50m 触发"收束模式")。
3. **全员停滞**:连续 T 分钟无新增有效条目且无活跃 claim(Merlin 判定),提前止损并输出当前最佳假设。

### 6.2 收束模式(时间快到时)

时间进入最后阶段,Merlin 切换全员策略:停止发散,集中火力到**当前置信度最高、认可数最多**的一条线,所有骑士转为"钻探/缝合"协助它闭环。避免"4 小时到了还在广撒网"。

### 6.3 死路检测的具体信号(Merlin 规则)

- 某条 hypothesis 的 challenge 数 ≥ endorse 数,且 X 分钟无新 artifact → 转 `DEAD_END`。
- 某骑士对同一子图连续 K 个 cycle 无产出 → 判定该线索对该姿态枯竭,重新指向。
- 活跃 claim 的标签集合基尼系数过高(全挤一处)→ 触发强制分散。

---

## 7. 沙箱与工具

所有骑士共享同一套工具箱(能力,而非领域归属):

- **shell**:任意命令执行(在隔离沙箱工作目录内)
- **文件操作**:读写附件、中间产物
- **网络**:HTTP 请求、连接靶机端口
- **CTF 常用工具预装**:`pwntools`、`binwalk`、`file`、`strings`、`ghidra`/`radare2`/`objdump`、`sqlmap`、`nmap`、`openssl`、`python` + 常用库(pycryptodome、requests、z3)
- **黑板操作**(结构化 JSON):`post_entry / endorse / challenge / claim`

**沙箱与权限是重活**(已确认要真沙箱):
- 每场比赛一个隔离容器/工作目录,附件拷入,产物留内。
- 网络访问按赛题需要放行(靶机 IP/端口),避免误伤。
- 工具调用有预算(per cycle / per knight),防止单个骑士烧光时间与 token。

---

## 8. 核心数据结构总览

```
Board
 ├─ entries: dict[id, BoardEntry]      # append-mostly
 ├─ index: 按 tag / type / author 的倒排,供 digest 快速生成
 └─ lock: asyncio.Lock

KnightPolicy   # §2.1,5 份实例
KnightSession  # 每骑士:Codex CLI runner + policy + 当前 claim
MerlinState    # 上一次 tick 的黑板快照、死路集合、停滞计数
Timeline       # 全程事件日志,用于复盘报告
```

---

## 9. 4 小时时间线(系统运行节奏)

| 阶段 | 时间 | 系统行为 |
|---|---|---|
| 发牌 | 0–2min | Kay 摄入题目、拷附件、初始化黑板、召集 |
| 侦察爆发 | 2–20min | Gawain 主导广度扫荡,Percival 试低垂果实,黑板快速填满 FACT |
| 发散攻坚 | 20min–3h | 五姿态并行,Merlin 持续去重/防撞路/派方向,假设→工件迭代 |
| 收束 | 3h–3h50m | Merlin 切收束模式,火力集中到最强线索 |
| 止损/散会 | 3h50m–4h | 拿到 flag 即散;否则输出最佳假设与完整 timeline |

---

## 10. 分阶段实施路线

**Phase 1 — 黑板 + 协议(最难也最核心,先做)**
- 实现 Board 数据结构、EntryType、6 个黑板工具、digest 生成。
- 单元测试:多协程并发读写黑板不丢条目、endorse/challenge/claim 正确。
- 里程碑:无 LLM,用脚本模拟骑士读写,验证协作机制本身正确。

**Phase 2 — 骑士 + Kay 主循环**
- 用 Codex CLI 实现 5 骑士(policy 渲染 prompt),接沙箱工具与结构化黑板操作回放。
- Kay 发牌 + 并发主循环 + Arthur 基础 flag 校验。
- 里程碑:跑通一道简单题(如一个 base64/凯撒的 Misc 或简单 Web)。

**Phase 3 — Merlin 元认知**
- 去重、死路检测、digest 优化、重新指向、收束模式。
- 里程碑:在一道"有明显死路陷阱"的题上,验证 Merlin 能防止全员撞路。

**Phase 4 — 加固**
- 沙箱隔离与权限、工具预算、token 预算、复盘报告、姿态池化(Merlin 多开同姿态)。

---

## 11. 主要风险与对策

| 风险 | 后果 | 对策 |
|---|---|---|
| **回音室**:骑士互相附和,多样性坍缩 | 5 个变 1 个,浪费 token | 性格=硬旋钮(§2.1);Mordred 天生唱反调;challenge 必带理由 |
| **Token 爆炸**:自由交流=全量广播 | 4h 内烧光预算 | digest 按需投喂(§3.4);tool_output 折叠;每骑士上下文独立且有预算 |
| **全员撞路**:都挤同一条错线 | 并行退化成串行 | Merlin 死路检测 + 强制分散(§6.3);claim 防撞车 |
| **卡住无出口** | 空转到超时 | Merlin 重新指向 + 收束模式(§6.2) |
| **假 flag / 幻觉** | 误报散会 | Arthur 独立验证(格式+真提交);flag_candidate 与 resolved 分离 |
| **沙箱逃逸/误伤** | 安全与合规 | 隔离容器、网络白名单、只在授权靶机上操作 |

---

## 12. 待定 / 下一步决策

- Phase 1 的黑板要不要持久化(便于崩溃恢复与复盘)?建议:JSONL append,天然可复盘。
- Merlin 的 tick 用定时还是"每 M 次写入触发"?建议:两者结合,写入触发为主、定时兜底。
- 是否需要人类"观战 + 干预"接口(把人当第六个可投喂条目的角色)?建议 Phase 4 可选。

---

*本文档为设计评审稿。确认方向后,建议从 Phase 1(黑板+协议)开始落地——它是整套系统正确性的地基,且可以完全脱离 LLM 先验证。*

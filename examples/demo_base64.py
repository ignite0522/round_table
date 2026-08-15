"""端到端脚本演示(无 LLM):五骑士协作解一道 base64 题。

这不是玩具流程走过场,而是**真的让协作机制决定结果**:
- 题目:附件是一段 base64,解码后是 flag。
- Gawain 侦察出『这看起来像 base64』的 FACT。
- Percival 走正门:直接尝试 base64 解码 —— 但故意先解错一层(证明单打独斗会失败)。
- Mordred 怀疑:challenge Percival 的错误结论。
- Lancelot 认领线索深钻:正确解码,产出 flag_candidate。
- Tristan 缝合:把 Gawain 的 fact + Lancelot 的产物串起来 endorse。
- Merlin 全程去重/防撞路;Arthur 验旗散会。

运行:  python -m examples.demo_base64
"""

from __future__ import annotations

import asyncio
import base64
import itertools

from roundtable.core import Board, BoardTools, EntryType
from roundtable.knights import ALL_KNIGHTS, MockKnight
from roundtable.roles import Arthur, Kay, Merlin, Problem

# —— 题目:base64 编码的 flag（发牌器会把它作为附件内容放进沙箱）——
SECRET_FLAG = "flag{r0und_t4ble_kn1ghts_r1de}"
ENCODED = base64.b64encode(SECRET_FLAG.encode()).decode()   # 附件内容


# ————————————————————————— 各骑士的脚本化行为 —————————————————————————
# 每个 behavior 体现该姿态的**结构性差异**,而非文风差异。

def make_behaviors():
    state = {"cursor": itertools.count()}

    async def gawain(kn: MockKnight, digest):
        # 侦察兵:广度扫,只摆事实。第一轮产出『这是 base64』的观察,然后就没啥可扫了。
        if kn.total_posts == 0:
            await kn.tools.post_entry(
                type=EntryType.FACT,
                title=f"附件是一段疑似 base64 的字符串(长度 {len(ENCODED)},仅含 A-Za-z0-9+/=)",
                body=f"content={ENCODED}",
                confidence=0.6,
                tags=["recon", "base64", "encoding"],
            )
            await kn.tools.post_entry(
                type=EntryType.NEXT_STEP,
                title="建议:对附件做 base64 解码",
                confidence=0.6,
                tags=["base64", "decode"],
            )
            return 2
        return 0   # 之后空转(侦察兵天生浅尝辄止)—— 用于触发 Merlin 重新指向

    async def percival(kn: MockKnight, digest):
        # 走正门:信任出题人,直接解码。但第一轮『手滑』把结论下错(rot13 幻觉),
        # 以此证明:单个骑士会犯错,靠圆桌的 challenge 纠偏。
        if kn.total_posts == 0:
            await kn.tools.post_entry(
                type=EntryType.HYPOTHESIS,
                title="这多半是 ROT13,直接 rot 一下就是 flag",
                body="(Percival 的直觉,未验证)",
                confidence=0.55,
                tags=["intended", "decode"],
            )
            return 1
        return 0

    async def mordred(kn: MockKnight, digest):
        # 破坏者:怀疑一切。第一轮不动手,先找 Percival 那条可疑结论开怼。
        for ln in digest.top_entries + digest.relevant_entries:
            if "ROT13" in ln.title and ln.challenge_count == 0:
                await kn.tools.challenge(
                    ln.id, "字符集是标准 base64 表且以 '=' 结尾,是 base64 不是 ROT13。"
                )
                return 1
        return 0

    async def lancelot(kn: MockKnight, digest):
        # 钻探者:先读桌,挑最强的可执行线索认领,深钻到底 —— 真的解码,产出 flag。
        # 找一条 base64 相关的 next_step 或 fact 认领
        for ln in digest.open_next_steps + digest.top_entries:
            if "base64" in " ".join(ln.tags) or "base64" in ln.title.lower():
                if await kn.tools.claim(ln.id):
                    # 真解码(这是『沙箱工具』在 Phase 1 的替身)
                    decoded = base64.b64decode(ENCODED).decode()
                    art = await kn.tools.post_entry(
                        type=EntryType.ARTIFACT,
                        title="base64 解码成功",
                        body=f"decoded={decoded}",
                        confidence=0.9,
                        refs=[ln.id],
                        tags=["base64", "artifact"],
                    )
                    await kn.tools.post_entry(
                        type=EntryType.FLAG_CANDIDATE,
                        title=f"flag 候选:{decoded}",
                        body=decoded,
                        confidence=0.95,
                        refs=[art.id],
                        tags=["flag"],
                    )
                    return 2
        return 0

    async def tristan(kn: MockKnight, digest):
        # 缝合者:不开新线,只 endorse 把证据链闭合的条目(Gawain 的 fact ↔ Lancelot 的 artifact)。
        endorsed = 0
        for ln in digest.top_entries:
            if ln.type in ("artifact", "flag_candidate") and kn.name not in []:
                if await kn.tools.endorse(ln.id):
                    endorsed += 1
        return 1 if endorsed else 0

    return {
        "Gawain": gawain,
        "Percival": percival,
        "Mordred": mordred,
        "Lancelot": lancelot,
        "Tristan": tristan,
    }


async def main():
    board = Board(jsonl_path="examples/_run_base64.jsonl")
    behaviors = make_behaviors()

    knights = []
    for policy in ALL_KNIGHTS:
        tools = BoardTools(board, policy.name, knight_tags=policy.preferred_tags)
        knights.append(MockKnight(policy, tools, behaviors[policy.name]))

    merlin = Merlin(board, idle_threshold=2)
    arthur = Arthur(board)   # Phase 1:格式校验即通过
    kay = Kay(
        board, knights, merlin, arthur,
        max_cycles=15,          # 演示用硬上限
        merlin_tick_every=1,
        clock=_fake_clock(),    # 用假时钟,避免真等
    )

    problem = Problem(
        title="Baby Encoding",
        statement="附件里有一段字符串,解出 flag。",
        attachments=["challenge.txt"],
    )

    result = await kay.run(problem)

    print("=" * 60)
    print(f"结果: {'✔ 解出' if result.solved else '✘ 未解出'}")
    print(f"flag: {result.flag}")
    print(f"终止原因: {result.reason}  | cycles: {result.cycles}  | 黑板条目: {result.board_size}")
    print("=" * 60)
    print("\n—— 时间线(节选)——")
    for ev in kay.timeline:
        e = ev["event"]
        if e == "cycle":
            print(f"  cycle {ev['n']}: 本轮新增 {ev['posts']} 条")
        elif e == "merlin":
            extras = {k: v for k, v in ev.items() if k not in ('t', 'event', 'n')}
            print(f"    -> Merlin: {extras}")
        elif e == "flag":
            print(f"  🏁 Arthur 确认 flag: {ev['flag']} (cycle {ev['cycle']})")
        elif e == "adjourn":
            print(f"  🔚 散会: {ev['reason']}")

    print("\n—— 最终黑板 ——")
    for entry in board.all():
        tag = f" #{' #'.join(entry.tags)}" if entry.tags else ""
        print(f"  [{entry.id}] {entry.type.value:14s} {entry.author:9s} "
              f"(+{entry.endorse_count}/-{entry.challenge_count}) {entry.title}{tag}")

    assert result.solved, "演示应当解出 flag"
    assert result.flag == SECRET_FLAG, "解出的 flag 应与埋入的一致"
    print("\n✅ 协作机制验证通过:五姿态经由黑板协作,Percival 的错误结论被 Mordred 纠偏,"
          "Lancelot 深钻产出正确 flag,Arthur 验旗散会。")


def _fake_clock():
    """单调递增假时钟:每次调用 +1s,让演示瞬间跑完而非真等 4 小时。"""
    counter = itertools.count(0, 1)
    return lambda: float(next(counter))


if __name__ == "__main__":
    asyncio.run(main())

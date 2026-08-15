# 圆桌骑士 · 构建状态

> 配套设计文档:`../DESIGN_圆桌骑士.md`。本文件记录已落地的代码与验证状态。

## 已完成

### Phase 1 —— 黑板 + 协议 + 脚本骑士(零 LLM,已端到端验证 ✅)

| 模块 | 文件 | 状态 |
|---|---|---|
| 条目类型/结构 | `roundtable/core/entry.py` | ✅ 7 类型、endorse/challenge/claim、score |
| 黑板 | `roundtable/core/board.py` | ✅ append-mostly、asyncio.Lock 并发安全、JSONL 持久化+replay、倒排索引 |
| 桌面简报 | `roundtable/core/digest.py` | ✅ 按需投喂、死路必给、body 不泄漏 |
| 黑板工具接口 | `roundtable/core/tools.py` | ✅ 6 工具,绑定骑士身份 |
| 骑士旋钮 | `roundtable/knights/policy.py` | ✅ 性格=策略先验,渲染 system prompt |
| 五骑士配置 | `roundtable/knights/roster.py` | ✅ Gawain/Percival/Mordred/Lancelot/Tristan |
| 脚本骑士 | `roundtable/knights/mock.py` | ✅ 可插拔 behavior,无 LLM |
| Merlin | `roundtable/roles/merlin.py` | ✅ 死路检测/去重/防撞路/重新指向/收束模式 |
| Arthur | `roundtable/roles/arthur.py` | ✅ 格式校验+真验证器钩子+幻觉隔离 |
| Kay | `roundtable/roles/kay.py` | ✅ 发牌+并发主循环+终止判定+骑士生命周期 |
| 测试 | `tests/` | ✅ 28 passed |
| 端到端演示 | `examples/demo_base64.py` | ✅ 五骑士经黑板协作解出 flag |

**验证结论**:`python -m examples.demo_base64` 端到端跑通——Gawain 侦察出 base64 事实,
Percival 走正门但错判 ROT13,Mordred challenge 纠偏,Lancelot 认领深钻解码产出 flag_candidate,
Tristan endorse 闭链,Arthur 验旗散会。**协作机制本身正确,与 LLM 无关。**

### Phase 2 —— 真骑士(Codex CLI)

| 模块 | 文件 | 状态 |
|---|---|---|
| Codex 骑士 | `roundtable/knights/codex_knight.py` | ✅ policy→prompt,`codex exec` 执行 cycle,JSON 黑板操作回放 |
| 组装器 | `roundtable/assemble.py` | ✅ assemble_mock / assemble_codex |
| 真骑士入口 | `examples/run_ctf.py` | ✅ CLI:--title/--attach/--cwd/--model... |

- Codex CLI 版本路径:`codex exec --skip-git-repo-check --sandbox workspace-write --output-schema ...`。
- 落地方式:每个 cycle 将 policy + digest + Merlin 指令交给 Codex,最终 JSON 返回黑板操作。
- 旧 SDK 路径已移除,默认入口已切到 Codex。

## 运行方式

```bash
cd round_table
python -m pytest tests/ -q          # 28 passed
python -m examples.demo_base64      # 零 LLM 端到端演示

# 真骑士(需 Codex CLI 已安装并登录)
python -m examples.run_ctf --title "Baby RSA" \
    --statement "附件求 flag" --attach ./work/chall.py --cwd ./work
```

## 下一步(未完成)

- Phase 2 完整实跑:五个 Codex 真骑士**并发**跑通一道真题。
- Phase 3 增强:Merlin 语义级去重(接入轻量 LLM,`hook_semantic_dedup`)。
- Phase 4 加固:沙箱网络白名单、per-knight token/工具预算硬限、姿态池化(同姿态多开)、复盘报告生成器。

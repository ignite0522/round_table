# 圆桌骑士 (Round Table)

一个基于**黑板架构**的多智能体 CTF 协作求解系统。一群"进攻姿态各异"的骑士围坐圆桌,面对**同一道题**,各自从不同角度进攻,把重要发现放上桌,彼此自由接纳(endorse)或质疑(challenge),直到 flag 出现,Arthur 宣布散会。

设计文档见仓库根目录 `DESIGN_圆桌骑士.md`。

## 四条设计铁律

1. **黑板是唯一真相源,不是聊天室** —— 骑士只读写结构化条目。
2. **性格 = 策略先验(旋钮),不是角色扮演台词** —— 避免 5 个换皮 LLM。
3. **不按题目类别分工,按进攻姿态分** —— 单题全员同目标。
4. **难点是"卡住怎么办",不是"找到就结束"** —— 这是 Merlin 的价值。

## 架构

| 角色 | 组件 | 职责 |
|---|---|---|
| Kay | Orchestrator | 发牌、驱动主循环、终止判定 |
| 圆桌 | Blackboard | 结构化条目的共享真相源 |
| 5 骑士 | Knight | 按姿态进攻,读写黑板 |
| Merlin | 元认知层 | 去重、死路检测、digest、防撞路 |
| Arthur | 仲裁 | 验证 flag,宣布散会 |

**五骑士(进攻姿态)**:Gawain 工具师 · Percival 走正门 · Mordred 逆向出题人 · Lancelot 单线死磕 · Tristan 侧向缝合。

## 目录结构

```
roundtable/
  core/        黑板、条目类型、工具接口、digest
  knights/     KnightPolicy 旋钮 + 五骑士配置 + 骑士实现(mock / Codex)
  roles/       Kay / Merlin / Arthur
  sandbox/     沙箱工具(Phase 2+)
tests/         单元测试与协作机制验证
examples/      端到端演示题目
```

## 开发阶段

- **Phase 1**(当前):黑板 + 协议 + 脚本模拟骑士(无 LLM 即可验证协作骨架)
- **Phase 2**:Kay 主循环 + Arthur + 接入 Codex CLI 真骑士 + 沙箱
- **Phase 3**:Merlin 元认知(去重/死路/收束)
- **Phase 4**:加固(沙箱隔离、预算、姿态池化、复盘报告)

## 快速开始(Phase 1,无需 LLM / API Key)

```bash
cd round_table
python -m pytest tests/ -v          # 跑协作机制测试
python -m examples.demo_base64      # 脚本模拟骑士端到端跑通一道简单题
```

## Kali Worker(第一版)

当前仓库提供了一版自建的 `Kali-lite` worker 镜像定义,目标是给圆桌骑士提供一个
预装常用 CTF/Web 安全工具的容器工位,同时保留项目代码在宿主机、运行时挂载进容器。

### 已安装工具

- 通用:`curl` `jq` `ripgrep` `fd` `git` `python3` `pip` `nodejs` `npm`
- Web/CTF:`nmap` `naabu` `sqlmap` `nikto` `dirsearch` `ffuf` `gobuster` `feroxbuster` `wfuzz`
- 其他:`netcat` `ncat` `binwalk` `exiftool` `xxd`
- Agent CLI:`codex`

注意: Dockerfile 里会在构建阶段移除 `nmap` 二进制的 file capabilities,避免它在 `NoNewPrivs` 一类容器限制下直接起不来。重建镜像后,`nmap` 应可作为普通用户态工具使用; 涉及原始套接字/特权扫描能力时仍可能受限。端口/服务侦察依然推荐优先配合 `naabu`、`ncat`、`nc`、`curl`、`openssl s_client`、`httpx`、`whatweb`。

### 构建镜像

```bash
./scripts/build_roundtable_kali.sh
```

如需自定义 tag:

```bash
./scripts/build_roundtable_kali.sh roundtable-kali:dev
```

### 进入容器

下面命令会:

- 把仓库挂载到容器内 `/opt/roundtable`
- 把工作目录挂载到容器内 `/workspace`
- 把宿主机 `CODEX_HOME` 或默认 `~/.codex` 只读挂载到 `/host-codex-home`
- 首次启动时把 `auth.json` 复制进容器用户自己的 `~/.codex`

```bash
./scripts/run_roundtable_kali.sh
```

指定工作目录:

```bash
./scripts/run_roundtable_kali.sh ./round_table_work/run-demo bash
```

进容器后,你可以直接验证工具和 Codex:

```bash
codex --version
naabu -version
ffuf -V
```

## 上传到 GitHub 时要放什么

这个项目里的 Docker 不建议把已经构建好的镜像本体提交到 GitHub 仓库。通常只需要提交:

- 项目代码
- `docker/roundtable-kali/Dockerfile`
- `docker/roundtable-kali/entrypoint.sh`
- `scripts/build_roundtable_kali.sh`
- `scripts/run_roundtable_kali.sh`
- 本 README

也就是说,仓库里放的是**镜像构建配方**,不是本地已经 build 完的镜像 layer / cache / 容器数据。

### 推荐提交流程

```bash
git add .
git commit -m "Prepare round table for GitHub"
git push origin main
```

### 别提交这些

- `round_table_work/`
- 本地测试日志
- Docker build cache
- 本机生成的临时文件

这些内容已经在 `.gitignore` 里做了基础忽略。

## 让别人复现 Docker

别人拿到仓库后,正常只需要:

```bash
git clone <your-repo-url>
cd round_table
./scripts/build_roundtable_kali.sh
```

如果你后面希望别人不用本地构建,可以再把镜像推到 Docker Hub 或 `ghcr.io`,但那是**镜像仓库**的事情,不是 GitHub 代码仓库本身要存放的内容。

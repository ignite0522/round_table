from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
]


def ensure_dir() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def setup_matplotlib() -> None:
    font_family = "DejaVu Sans"
    for font_path in FONT_CANDIDATES:
        if font_path.exists():
            font_manager.fontManager.addfont(font_path)
            font_family = font_manager.FontProperties(fname=font_path).get_name()
            break
    plt.rcParams.update(
        {
            "font.family": font_family,
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.titlesize": 14,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "figure.dpi": 180,
        }
    )


def rounded_box(ax, xy, width, height, text, fc, ec="#d0d7e2", lw=1.5, fs=11, weight="bold"):
    box = patches.FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(box)
    ax.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        weight=weight,
        color="#1f2937",
    )
    return box


def arrow(ax, start, end, color="#4063d8", lw=1.8, style="-|>", rad=0.0):
    ax.add_patch(
        patches.FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=14,
            linewidth=lw,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def render_framework() -> None:
    fig = plt.figure(figsize=(14, 8))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.text(0.05, 0.95, "图 1  圆桌骑士总体框架", fontsize=17, weight="bold", color="#111827")
    fig.text(
        0.05,
        0.915,
        "以结构化黑板为共享记忆，由路线级元控制器协调多智能体搜索、Kali 工具执行与结果验证。",
        fontsize=11,
        color="#4b5563",
    )

    outer = patches.FancyBboxPatch(
        (0.18, 0.30),
        0.56,
        0.50,
        boxstyle="round,pad=0.018,rounding_size=0.03",
        linewidth=1.5,
        linestyle=(0, (4, 3)),
        edgecolor="#b6becb",
        facecolor="#f8fafc",
    )
    ax.add_patch(outer)

    rounded_box(ax, (0.05, 0.50), 0.10, 0.22, "任务输入\nURL / 附件\n题目描述", "#f5f3ff", ec="#9b87f5")
    rounded_box(ax, (0.05, 0.34), 0.10, 0.12, "人工指令\n最高优先级", "#fef3c7", ec="#f59e0b")

    center = patches.Circle((0.46, 0.54), 0.115, edgecolor="#d1d5db", facecolor="#ffffff", linewidth=2)
    ax.add_patch(center)
    ax.text(0.46, 0.565, "Kay + Merlin", ha="center", va="center", fontsize=16, weight="bold", color="#1d4ed8")
    ax.text(0.46, 0.525, "推进轮次\n评估路线\n重定向算力", ha="center", va="center", fontsize=10, color="#374151")

    rounded_box(ax, (0.23, 0.63), 0.16, 0.11, "1  检索\n黑板事实 / 笔记\nKali 观测", "#eaf2ff", ec="#7aa2f7")
    rounded_box(ax, (0.56, 0.63), 0.14, 0.11, "2  规划\n生成路线级\n下一步动作", "#eaf7ee", ec="#66bb6a")
    rounded_box(ax, (0.58, 0.40), 0.14, 0.11, "3  协调\n分派骑士\n启动新轮次", "#fff4e5", ec="#fb923c")
    rounded_box(ax, (0.24, 0.39), 0.15, 0.11, "4  蒸馏\n沉淀证据\n更新精英候选", "#f3e8ff", ec="#a855f7")

    arrow(ax, (0.39, 0.69), (0.43, 0.62), rad=-0.15)
    arrow(ax, (0.57, 0.68), (0.54, 0.63), color="#2f855a", rad=0.12)
    arrow(ax, (0.59, 0.46), (0.54, 0.49), color="#ea7a1f", rad=0.10)
    arrow(ax, (0.39, 0.45), (0.41, 0.49), color="#9333ea", rad=-0.12)

    rounded_box(ax, (0.79, 0.64), 0.15, 0.12, "黑板记忆\n事实 / 工件 /\n死路 / Flag", "#eef7ff", ec="#60a5fa")
    rounded_box(ax, (0.79, 0.48), 0.15, 0.12, "技能与工具库\nKali 工具 / Payload /\n知识库", "#effcf3", ec="#4ade80")
    rounded_box(ax, (0.79, 0.32), 0.15, 0.12, "搜索策略库\n偏好 / 重排 /\n搜索压力", "#fff1f2", ec="#fb7185")

    arrow(ax, (0.74, 0.69), (0.79, 0.69), color="#2563eb")
    arrow(ax, (0.79, 0.66), (0.74, 0.66), color="#2563eb")
    arrow(ax, (0.72, 0.54), (0.79, 0.54), color="#16a34a")
    arrow(ax, (0.79, 0.51), (0.72, 0.51), color="#16a34a")
    arrow(ax, (0.72, 0.39), (0.79, 0.39), color="#ef4444")
    arrow(ax, (0.79, 0.36), (0.72, 0.36), color="#ef4444")

    bottom_y = 0.13
    rounded_box(ax, (0.07, bottom_y), 0.14, 0.09, "输入与边界", "#ffffff", ec="#0f4c81", fs=12)
    rounded_box(ax, (0.28, bottom_y), 0.14, 0.09, "阶段 1\n侦察 / 构思", "#ffffff", ec="#0f4c81", fs=12)
    rounded_box(ax, (0.46, bottom_y), 0.14, 0.09, "阶段 2\n利用 / 复现", "#ffffff", ec="#0f4c81", fs=12)
    rounded_box(ax, (0.64, bottom_y), 0.14, 0.09, "阶段 3\n验证 / 报告", "#ffffff", ec="#0f4c81", fs=12)
    rounded_box(ax, (0.84, bottom_y), 0.09, 0.09, "Flag", "#ffffff", ec="#0f4c81", fs=13)
    for x0, x1 in [(0.21, 0.28), (0.42, 0.46), (0.60, 0.64), (0.78, 0.84)]:
        arrow(ax, (x0, bottom_y + 0.045), (x1, bottom_y + 0.045), color="#f97316", lw=2.5)

    knight_names = ["Gawain", "Percival", "Mordred", "Lancelot", "Tristan"]
    knight_colors = ["#dbeafe", "#dcfce7", "#fee2e2", "#ede9fe", "#fef3c7"]
    x_positions = [0.25, 0.35, 0.46, 0.57, 0.67]
    for x, name, color in zip(x_positions, knight_names, knight_colors):
        rounded_box(ax, (x, 0.25), 0.085, 0.05, name, color, ec="#cbd5e1", fs=10)
        arrow(ax, (x + 0.042, 0.30), (0.46, 0.425), color="#94a3b8", lw=1.2)

    ax.text(0.05, 0.07, "视觉结构参考 NanoResearch Figure 2 的多存储、多阶段系统图表达。", fontsize=9, color="#6b7280")

    fig.savefig(ASSET_DIR / "round_table_framework.png", bbox_inches="tight")
    plt.close(fig)


def render_main_results() -> None:
    methods = ["单智能体", "平铺式五智能体", "圆桌骑士"]
    metrics = ["解题率", "Flag 精度", "路线召回率", "运行稳定性"]
    values = np.array(
        [
            [31.4, 88.1, 42.2, 54.6],
            [42.9, 91.3, 58.7, 68.2],
            [57.8, 97.2, 74.5, 81.6],
        ]
    )

    fig = plt.figure(figsize=(14, 7))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.4, 1.0], wspace=0.18)
    ax = fig.add_subplot(gs[0, 0])
    tab_ax = fig.add_subplot(gs[0, 1])

    x = np.arange(len(metrics))
    width = 0.22
    colors = ["#94a3b8", "#60a5fa", "#1d4ed8"]
    for i, method in enumerate(methods):
        ax.bar(x + (i - 1) * width, values[i], width=width, label=method, color=colors[i], edgecolor="white")
        for j, val in enumerate(values[i]):
            ax.text(x[j] + (i - 1) * width, val + 1.2, f"{val:.1f}", ha="center", va="bottom", fontsize=9, color="#334155")

    ax.set_ylim(0, 105)
    ax.set_ylabel("得分 / 百分比")
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_title("图 2  代表性系统指标的示意性主结果", fontsize=15)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False, loc="upper left")

    tab_ax.axis("off")
    table_data = [
        ["单智能体", "31.4", "16.8", "24.7", "88.1"],
        ["平铺式五智能体", "42.9", "13.2", "19.5", "91.3"],
        ["圆桌骑士", "57.8", "9.6", "8.4", "97.2"],
    ]
    col_labels = ["方法", "解题率", "中位轮次", "重复工作", "Flag 精度"]
    table = tab_ax.table(
        cellText=table_data,
        colLabels=col_labels,
        colWidths=[0.26, 0.185, 0.185, 0.185, 0.185],
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.1, 1.8)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#dbe3ee")
        if row == 0:
            cell.set_facecolor("#e8eefc")
            cell.set_text_props(weight="bold", color="#1f2937")
        elif row == 3:
            cell.set_facecolor("#edf4ff")
        else:
            cell.set_facecolor("#ffffff")

    tab_ax.text(
        0.5,
        0.12,
        "README 示意数据，仅用于展示设计目标与图表版式。",
        ha="center",
        va="center",
        fontsize=9,
        color="#6b7280",
    )

    fig.savefig(ASSET_DIR / "main_results.png", bbox_inches="tight")
    plt.close(fig)


def render_ablation() -> None:
    variants = ["完整系统", "移除 Merlin 重排", "移除 Arthur 验证", "移除结构化黑板"]
    solve = [57.8, 51.6, 54.2, 46.3]
    stability = [81.6, 73.1, 68.5, 61.9]
    y = np.arange(len(variants))

    fig = plt.figure(figsize=(14, 6.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.2, 1.0], wspace=0.18)
    ax = fig.add_subplot(gs[0, 0])
    tab_ax = fig.add_subplot(gs[0, 1])

    ax.barh(y + 0.17, solve, height=0.32, color="#1d4ed8", label="解题率")
    ax.barh(y - 0.17, stability, height=0.32, color="#93c5fd", label="稳定性")
    for i, (s1, s2) in enumerate(zip(solve, stability)):
        ax.text(s1 + 0.8, i + 0.17, f"{s1:.1f}", va="center", fontsize=9)
        ax.text(s2 + 0.8, i - 0.17, f"{s2:.1f}", va="center", fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels(variants)
    ax.set_xlim(0, 100)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.set_xlabel("得分 / 百分比")
    ax.set_title("图 3  关键协同组件的示意性消融结果", fontsize=15)
    ax.legend(frameon=False, loc="lower right")
    ax.invert_yaxis()

    tab_ax.axis("off")
    notes = [
        ["完整系统", "广度与收敛性平衡最佳"],
        ["移除 Merlin 重排", "路线优先级选择能力下降"],
        ["移除 Arthur 验证", "终止判断噪声增加"],
        ["移除结构化黑板", "证据复用下降，重复工作增多"],
    ]
    table = tab_ax.table(cellText=notes, colLabels=["消融设置", "现象"], loc="center", cellLoc="left", colLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 2.2)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#dbe3ee")
        if row == 0:
            cell.set_facecolor("#eef2ff")
            cell.set_text_props(weight="bold")
        elif row == 1:
            cell.set_facecolor("#f8fbff")
        else:
            cell.set_facecolor("#ffffff")

    fig.savefig(ASSET_DIR / "ablation_results.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ensure_dir()
    setup_matplotlib()
    render_framework()
    render_main_results()
    render_ablation()
    print(f"Rendered assets to {ASSET_DIR}")


if __name__ == "__main__":
    main()

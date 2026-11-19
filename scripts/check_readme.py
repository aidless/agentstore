#!/usr/bin/env python3
"""核对 README 里那些"能跑出来的数字"是否与本仓代码一致。

为什么需要这个：README 首屏写着「约 1400 行、零依赖」，中段贴着 quickstart
与 demo 的真实输出，末尾还有一份 16 个 MCP server 的审查表。这些数最典型的
腐化方式不是写错，而是**改完代码忘了改文档**——读者拿到的是精确但过期的自述。

只核对**可复算**的项：包行数、依赖数、quickstart 生成文件数、demo 的账单
与幂等行数、审查表的分母与各项计数。不核对叙述性判断。

退出码：0 = 全部一致；1 = 有不一致；2 = 用法错/缺依赖。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

ROW = re.compile(r"^\| (\S[\w-]*) \| [^|]* \| (\d+) \|", re.M)
MCP_ROW = re.compile(r"^\| (.+?) \| \*{0,2}(\d+) / (\d+)\*{0,2} \|", re.M)
LINES_CLAIM = re.compile(r"约 (\d+) 行")
DEPS = re.compile(r"dependencies\s*=\s*\[(.*?)\]", re.S)


def _permission_table_only(text: str) -> str:
    """只取「附：为什么要有权限声明」那一节，避免别的表长得像被一起扫进来。"""
    marker = "## 附：为什么要有权限声明"
    i = text.find(marker)
    return text[i:] if i >= 0 else text


def _run_demo(db: Path) -> str:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT)
    r = subprocess.run(
        [sys.executable, "-m", "agentstore.cli", "demo", "--db", str(db)],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    return r.stdout


def _run_quickstart(target: Path) -> str:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT)
    r = subprocess.run(
        [sys.executable, "-m", "agentstore.cli", "quickstart", "--dir", str(target)],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    return r.stdout


def _run_generated_runpy(target: Path) -> str:
    """quickstart 生成的 run.py 在含反斜杠的工作区路径下用 PYTHONPATH 会失败，
    改用 sys.path + __file__ 注入在同一进程 exec，拿到与 README 一致的真账单。"""
    if not (target / "run.py").exists():
        return ""
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r}); sys.argv=['run.py']; "
        f"exec(compile(open('run.py').read(),'run.py','exec'), "
        f"{{'__file__':'run.py','__name__':'__main__'}})"
    )
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = ""
    r = subprocess.run([sys.executable, "-c", code], cwd=target,
                       capture_output=True, text=True, env=env)
    return r.stdout


def actual() -> dict:
    """从代码与真跑输出重算 README 引用的数。"""
    py_files = list((ROOT / "agentstore").rglob("*.py"))
    lines = sum(len(p.read_text().splitlines()) for p in py_files)

    pyproject = (ROOT / "pyproject.toml").read_text()
    m = DEPS.search(pyproject)
    dep_count = len(re.findall(r'"([^"]+)"', m.group(1))) if m else 0

    with tempfile.TemporaryDirectory() as td:
        qs_dir = Path(td) / "qs"
        qs = _run_quickstart(qs_dir)
        mqs = re.search(r"新建/覆盖 (\d+) 个，跳过 (\d+) 个", qs)
        qs_created = int(mqs.group(1)) if mqs else -1
        qs_skipped = int(mqs.group(2)) if mqs else -1
        runpy_out = _run_generated_runpy(qs_dir)

        demo = _run_demo(Path(td) / "demo.db")

    # README 的 $0.05 账单是 quickstart 生成的 run.py 输出的（hello 一单 5¢），
    # 不是 cli demo 的 $10.00 —— 取错底物会把正确文档判成漂移。
    total = re.search(r"合计应付 \*\*\$([\d.]+)\*\*", runpy_out)
    fee = re.search(r"平台抽成 (\d+)%", runpy_out)
    usage = re.search(r"库里的用量行数：(\d+)", runpy_out)
    # cli demo 单独留作参考（README 贴的是它的命令，不是它的输出）
    demo_total = re.search(r"合计应付 \*\*\$([\d.]+)\*\*", demo)

    # 权限审查表：scripts/real_manifests.py 的落盘结果
    # 优先读落盘 JSON（若有），否则只从 README 自身解析分母做一致性自检
    audit: dict[str, tuple[int, int]] = {}
    for p in [ROOT / "data" / "raw" / "manifest_audit.json",
              ROOT / "data" / "manifest_audit.json"]:
        if p.exists():
            raw = json.loads(p.read_text())
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        audit[k] = (int(v[0]), int(v[1]))
            break

    return {
        "lines": lines,
        "deps": dep_count,
        "qs_created": qs_created,
        "qs_skipped": qs_skipped,
        "demo_total": float(total.group(1)) if total else -1.0,
        "demo_fee": int(fee.group(1)) if fee else -1,
        "demo_usage": int(usage.group(1)) if usage else None,
        "cli_demo_total": float(demo_total.group(1)) if demo_total else None,
        "audit": audit,
    }


def compare(text: str, got: dict) -> list[str]:
    problems: list[str] = []

    # 行数（「约 1400 行」）——允许 5% 漂移，措辞本来就是"约"
    m = LINES_CLAIM.search(text)
    if not m:
        problems.append("找不到包行数（「约 N 行」的措辞，改了就同步更新匹配式）")
    else:
        written = int(m.group(1))
        if abs(written - got["lines"]) > max(50, written * 0.05):
            problems.append(f"包行数：README 写约 {written}，实测 {got['lines']}")

    # 依赖数（README 说「零外部依赖」）
    if got["deps"] != 0 and re.search(r"零外部依赖|只用 Python 标准库", text):
        problems.append(f"README 声称零外部依赖，pyproject 里有 {got['deps']} 个")

    # quickstart 生成数
    m = re.search(r"新建/覆盖 (\d+) 个，跳过 (\d+) 个", text)
    if m:
        if (int(m.group(1)), int(m.group(2))) != (got["qs_created"], got["qs_skipped"]):
            problems.append(
                f"quickstart：README 写 新建 {m.group(1)} 跳过 {m.group(2)}，"
                f"实测 {got['qs_created']} / {got['qs_skipped']}"
            )
    else:
        problems.append("找不到 quickstart 输出行（「新建/覆盖 N 个，跳过 M 个」）")

    # demo 账单合计与抽成
    m = re.search(r"合计应付 \*\*\$([\d.]+)\*\*（平台抽成 (\d+)%）", text)
    if m:
        if abs(float(m.group(1)) - got["demo_total"]) > 0.001:
            problems.append(f"demo 合计应付：README 写 ${m.group(1)}，实测 ${got['demo_total']:.2f}")
        if int(m.group(2)) != got["demo_fee"]:
            problems.append(f"demo 平台抽成：README 写 {m.group(2)}%，实测 {got['demo_fee']}%")
    else:
        problems.append("找不到 demo 账单合计行（「合计应付 **$X**（平台抽成 Y%）」）")

    # 三分钟段落里的 run.py 示例账单：合计 $0.05 / 平台 $0.01 / 开发者 $0.04 / 用量 1 行
    # 这段来自 quickstart 生成的 run.py，不是 cli demo，单独核对那张表
    for label, pattern, want in [
        ("示例账单应付", r"\| hello \| you \| 1 \| 1 \| \$([\d.]+) \|", 0.05),
        ("示例账单平台分成", r"\| hello \| you \| 1 \| 1 \| \$[\d.]+ \| \$([\d.]+) \|", 0.01),
        ("示例账单开发者应得", r"\| hello \| you \| 1 \| 1 \| \$[\d.]+ \| \$[\d.]+ \| \$([\d.]+) \|", 0.04),
    ]:
        mm = re.search(pattern, text)
        if mm and abs(float(mm.group(1)) - want) > 0.001:
            problems.append(f"{label}：README 写 ${mm.group(1)}，应为 ${want:.2f}（5¢ × 20% 分成）")

    if got["demo_usage"] is not None:
        mm = re.search(r"库里的用量行数：(\d+)", text)
        if mm and int(mm.group(1)) != got["demo_usage"]:
            problems.append(f"用量行数：README 写 {mm.group(1)}，实测 {got['demo_usage']}")

    # 权限审查表：分母必须一致；若有落盘数据，逐项比对
    mcp_rows = MCP_ROW.findall(_permission_table_only(text))
    if not mcp_rows:
        problems.append("找不到 MCP 权限审查表的计数行")
    else:
        denominators = {int(d) for _, _, d in mcp_rows}
        if len(denominators) != 1:
            problems.append(f"MCP 审查表分母不一致：{sorted(denominators)}")
        else:
            n = denominators.pop()
            for label, written, _ in mcp_rows:
                key = {
                    "清单里有任何权限字段": "with_permission",
                    "文档/依赖显示需要 API 密钥": "needs_key",
                    "需要写文件": "writes_file",
                    "版本可固定": "pinned_version",
                }.get(label)
                if key and key in got["audit"]:
                    want, want_n = got["audit"][key]
                    if (int(written), n) != (want, want_n):
                        problems.append(
                            f"MCP 审查表 `{label}`：README 写 {written}/{n}，落盘 {want}/{want_n}"
                        )

    return problems


def _selftest() -> int:
    got = {
        "lines": 1377, "deps": 0, "qs_created": 4, "qs_skipped": 0,
        "demo_total": 0.05, "demo_fee": 20, "demo_usage": 1,
        # 键名对应 compare 里 MCP_LABEL_TO_KEY 的英文映射值
        "audit": {
            "with_permission": (0, 16),
            "needs_key": (13, 16),
            "writes_file": (1, 16),
            "pinned_version": (9, 16),
        },
    }
    good = (
        "一个 agent 应用商店的最小内核：约 1400 行、零外部依赖、只用 Python 标准库。\n\n"
        "== quickstart: agentstore-quickstart（新建/覆盖 4 个，跳过 0 个）==\n\n"
        "| hello | you | 1 | 1 | $0.05 | $0.01 | $0.04 |\n\n"
        "库里的用量行数：1（重放与冲突都没有新增计费）\n\n"
        "合计应付 **$0.05**（平台抽成 20%）\n\n"
        "## 附：为什么要有权限声明\n\n"
        "| 指标 | 结果 |\n"
        "|---|---|\n"
        "| 清单里有任何权限字段 | **0 / 16** |\n"
        "| 文档/依赖显示需要 API 密钥 | 13 / 16 |\n"
        "| 需要写文件 | 1 / 16 |\n"
        "| 版本可固定（x.y.z） | 9 / 16 |\n"
    )
    cases: list[tuple[str, str, bool, str]] = [
        ("干净文本", good, False, "合规输入必须放行"),
        ("行数漂移", good.replace("约 1400 行", "约 2000 行"), True, "行数漂移必须报"),
        ("quickstart 漂移", good.replace("新建/覆盖 4 个", "新建/覆盖 5 个"), True, "生成数漂移必须报"),
        ("账单合计漂移", good.replace("合计应付 **$0.05**", "合计应付 **$12.00**"), True, "账单漂移必须报"),
        ("抽成漂移", good.replace("平台抽成 20%", "平台抽成 30%"), True, "抽成漂移必须报"),
        ("审查表分子漂移", good.replace("13 / 16", "14 / 16"), True, "审查表数字漂移必须报"),
        ("审查表分母漂移", good.replace("9 / 16 |", "9 / 20 |"), True, "分母漂移必须报"),
        ("别的表长得像", good.replace("## 附：为什么要有权限声明",
                                  "| 无关 | 99 / 100 |\n\n## 附：为什么要有权限声明"), False,
         "审查表外的计数行不报"),
    ]
    fails: list[str] = []
    for name, text, expect_bad, why in cases:
        problems = compare(text, got)
        if bool(problems) != expect_bad:
            fails.append(f"{name}（期望{'红' if expect_bad else '绿'}，实际 {problems or '绿'}；{why}）")
        else:
            print(f"  ✓ {name}：{'红了' if expect_bad else '放行'} —— {why}")

    real = compare(README.read_text(), actual())
    if real:
        fails.append(f"真实 README 与实测不一致：{real[:3]}")
    else:
        print("  ✓ 真实 README：行数/依赖/quickstart/demo/审查表全部重算一致")

    if fails:
        print(f"\n✗ selftest {len(fails)} 条不通过：")
        for f in fails:
            print("  " + f)
        return 1
    red = len([c for c in cases if c[2]])
    green = len([c for c in cases if not c[2]]) + 1
    print(f"\n✓ selftest 全通过（{red + green} 例：{red} 条必红 + {green} 条必绿）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核对 README 数字是否与本仓代码一致")
    ap.add_argument("--selftest", action="store_true", help="非空性反证自测")
    ap.add_argument("--readme", default=str(README))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    got = actual()
    print("实测：" + json.dumps({k: v for k, v in got.items() if k != "audit"}, ensure_ascii=False))
    problems = compare(Path(args.readme).read_text(), got)
    if problems:
        print("\nREADME 与代码不一致：")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("README 数字全部可复算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.chat_agent import run_chat_agent


def _read_text_from_stdin() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    print("请输入要分析的加密货币新闻 / 公告 / 链上事件：")
    print("提示：输入完成后按 Enter 提交。")
    return input("> ").strip()


def _print_report(report: dict[str, object]) -> None:
    print("\n========== CryptoRisk Chat Agent Report ==========")
    print(f"总结：{report.get('summary', '')}")
    print(f"是否有风险：{report.get('has_risk', False)}")
    print(f"风险分数：{report.get('risk_score', 0)}")
    print(f"风险等级：{report.get('risk_level', '')}")
    print(f"风险类别：{', '.join(str(item) for item in report.get('risk_categories', []))}")
    print(f"风险信号：{', '.join(str(item) for item in report.get('risk_signals', []))}")

    print("\n证据：")
    evidence_items = report.get("evidence", [])
    if isinstance(evidence_items, list) and evidence_items:
        for index, item in enumerate(evidence_items, start=1):
            if isinstance(item, dict):
                print(f"{index}. [{item.get('risk_category', '')}] {item.get('evidence_text', '')}")
                print(f"   说明：{item.get('explanation', '')}")
    else:
        print("- 暂无")

    print("\n可能影响：")
    for item in report.get("impact", []):
        print(f"- {item}")

    print("\n处置建议：")
    for index, item in enumerate(report.get("advice", []), start=1):
        print(f"{index}. {item}")

    print("\nJSON：")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CryptoRisk chat agent from terminal.")
    parser.add_argument("--text", help="新闻文本。没有传入时从终端输入。")
    args = parser.parse_args()

    text = args.text.strip() if args.text else _read_text_from_stdin()
    if not text:
        raise SystemExit("没有输入新闻文本，已退出。")

    report = run_chat_agent(text)
    _print_report(report)


if __name__ == "__main__":
    main()

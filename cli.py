# -*- coding: utf-8 -*-
"""命令行问答入口。

用法：
    python cli.py                     # 自动模式：连得上 TuGraph 就用真库，否则用离线模拟库
    python cli.py --mock              # 强制离线模拟库
    python cli.py --llm fake          # 强制离线规则模型（无 API Key 也能演示）
    python cli.py -q "癫痫有哪些症状？"  # 单次提问
    python cli.py --demo              # 跑一段固定脚本，方便截图写报告
"""
from __future__ import annotations

import argparse
import sys

from medkg.qa import QAEngine
from medkg.storage import GraphError, open_store
from medkg.t2c import Text2Cypher

BANNER = "===== 医学知识图谱问答系统 ====="

DEMO_QUESTIONS = [
    "癫痫要做什么检查？",
    "那属于哪个科室？",
    "冠心病有哪些症状？",
    "用什么药？",
    "哪些疾病会出现头痛？",
    "图谱里一共有多少种疾病？",
    "今天天气怎么样？",
]

COMMANDS = {
    "exit": "退出",
    "quit": "退出",
    "退出": "退出",
    "help": "查看示例问题",
    "帮助": "查看示例问题",
    "schema": "查看图谱结构",
    "结构": "查看图谱结构",
    "reset": "清空多轮上下文",
    "重置": "清空多轮上下文",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="医学知识图谱问答系统（Text2Cypher）")
    parser.add_argument("--mode", choices=["auto", "rest", "mock"], default=None,
                        help="图谱存储模式：auto/rest(TuGraph)/mock(离线)")
    parser.add_argument("--llm", choices=["auto", "real", "fake"], default=None,
                        help="模型模式：auto/real(调用 API)/fake(离线规则)")
    parser.add_argument("--mock", action="store_true", help="等同 --mode mock（离线模拟库）")
    parser.add_argument("--fake", action="store_true", help="等同 --llm fake（离线规则模型）")
    parser.add_argument("-q", "--question", action="append", default=None,
                        help="直接提问，可重复多次")
    parser.add_argument("--demo", action="store_true", help="运行内置演示脚本")
    parser.add_argument("--quiet", action="store_true", help="只输出答案")
    args = parser.parse_args(argv)
    if args.mock:
        args.mode = "mock"
    if args.fake:
        args.llm = "fake"
    return args


def print_answer(response) -> None:
    print()
    print(response.answer)
    if response.cypher:
        print(f"\nCypher：{response.cypher}")
    if response.elapsed_ms:
        print(f"耗时：{response.elapsed_ms:.0f} ms")
    print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store, note = open_store(mode=args.mode, verbose=not args.quiet)
    try:
        store.connect()
    except GraphError as exc:
        print(f"图谱连接失败：{exc}", file=sys.stderr)
        return 2

    dictionary = None
    from medkg.extract.dictionary import load_dictionary

    dictionary = load_dictionary()
    t2c = Text2Cypher(store=store, dictionary=dictionary, mode=args.llm, verbose=False)
    engine = QAEngine(store=store, dictionary=dictionary, t2c=t2c, verbose=not args.quiet)

    if not args.quiet:
        print(BANNER)
        print(f"图谱：{store.name}　节点 {store.count_nodes()} 个 / 关系 {store.count_edges()} 条")
        print(f"模型：{t2c.llm.model}（{t2c.llm.name}）")
        print("输入问题开始问答，exit 退出，help 查看示例。")

    if args.demo:
        try:
            for question in DEMO_QUESTIONS:
                print(f"\n问题> {question}")
                print_answer(engine.ask(question))
            print("问答结束。")
        finally:
            store.close()
        return 0

    if args.question:
        try:
            for question in args.question:
                print(f"\n问题> {question}")
                print_answer(engine.ask(question))
            print("问答结束。")
        finally:
            store.close()
        return 0

    while True:
        try:
            question = input("\n问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n问答结束。")
            break
        if not question:
            continue
        command = COMMANDS.get(question.lower(), COMMANDS.get(question))
        if command == "退出":
            print("问答结束。")
            break
        if command == "查看示例问题":
            from medkg.qa import HELP_TEXT

            print(HELP_TEXT)
            continue
        if command == "查看图谱结构":
            from medkg.schema import schema_card

            print(schema_card())
            continue
        if command == "清空多轮上下文":
            engine.reset()
            print("已清空上下文。")
            continue
        print_answer(engine.ask(question))
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
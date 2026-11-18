"""Command line interface:  python -m ayw <demo-data | check | ask | chat | eval> ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ayw import demo_data
from ayw.agent import Agent
from ayw.catalog import Catalog
from ayw.engine import Engine
from ayw.evaluate import OracleClient, load_adversarial, run_adversarial, run_eval
from ayw.golden import load_golden
from ayw.llm import OllamaClient

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "catalog" / "warehouse.yaml"
DEFAULT_GOLDEN = ROOT / "eval" / "golden.yaml"
DEFAULT_ADVERSARIAL = ROOT / "eval" / "adversarial.yaml"


def _agent(args, client=None) -> Agent:
    engine = Engine.from_warehouse(args.warehouse)
    catalog = Catalog.load(args.catalog)
    client = client or OllamaClient(args.model, host=args.host, num_ctx=args.num_ctx)
    return Agent(engine, catalog, client, max_repairs=args.repairs,
                 use_retrieval=not args.no_retrieval, use_examples=not args.no_examples)


def _print_answer(ans, limit: int = 20) -> None:
    print(f"\nSQL ({len(ans.attempts)} attempt{'s' if len(ans.attempts) != 1 else ''}, {ans.latency_s:.1f}s):\n{ans.sql}\n")
    if not ans.ok:
        print(f"No answer: {ans.error}")
        return
    print(" | ".join(ans.columns))
    for r in ans.rows[:limit]:
        print(" | ".join("" if v is None else str(v) for v in r))
    if len(ans.rows) > limit:
        print(f"... {len(ans.rows) - limit} more rows")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ayw", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, model=True):
        sp.add_argument("--warehouse", default="demo_warehouse", help="folder with the Parquet tables")
        sp.add_argument("--catalog", default=str(DEFAULT_CATALOG))
        if model:
            sp.add_argument("--model", default="qwen2.5-coder:3b", help="Ollama model name")
            sp.add_argument("--host", default="http://localhost:11434")
            sp.add_argument("--num-ctx", type=int, default=4096)
            sp.add_argument("--repairs", type=int, default=2, help="max self-correction attempts")
            sp.add_argument("--no-retrieval", action="store_true", help="give the model the whole schema")
            sp.add_argument("--no-examples", action="store_true", help="omit the few-shot examples")

    d = sub.add_parser("demo-data", help="generate a synthetic warehouse")
    d.add_argument("--out", default="demo_warehouse")
    d.add_argument("--events", type=int, default=20000)

    c = sub.add_parser("check", help="verify the catalog matches the warehouse columns")
    common(c, model=False)

    a = sub.add_parser("ask", help="ask one question")
    common(a)
    a.add_argument("question")

    ch = sub.add_parser("chat", help="interactive questions")
    common(ch)

    e = sub.add_parser("eval", help="run the golden set (and optionally the adversarial prompts)")
    common(e)
    e.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    e.add_argument("--out", default="results")
    e.add_argument("--limit", type=int, default=0, help="only the first N cases")
    e.add_argument("--adversarial", action="store_true")
    e.add_argument("--oracle", action="store_true", help="use reference SQL as the 'model' (validates the harness)")

    args = p.parse_args(argv)

    if args.cmd == "demo-data":
        out = demo_data.build(args.out, args.events)
        print(f"wrote demo warehouse to {out}")
        return 0

    if args.cmd == "check":
        eng = Engine.from_warehouse(args.warehouse)
        problems = Catalog.load(args.catalog).diff(eng.describe())
        eng.close()
        print("\n".join(problems) if problems else "catalog matches the warehouse")
        return 1 if problems else 0

    client = OracleClient(load_golden(args.golden)) if args.cmd == "eval" and args.oracle else None
    agent = _agent(args, client)
    try:
        if args.cmd == "ask":
            _print_answer(agent.ask(args.question))
        elif args.cmd == "chat":
            print(f"Connected to {agent.client.name}. Ask a question, or press Ctrl-D to quit.")
            while True:
                try:
                    q = input("\n> ").strip()
                except EOFError:
                    break
                if q:
                    _print_answer(agent.ask(q))
        else:
            cases = load_golden(args.golden)
            if args.limit:
                cases = cases[:args.limit]
            def progress(i, n, case, ok):
                print(f"[{i}/{n}] {case.id} {'ok ' if ok else 'FAIL'} {case.question[:70]}", file=sys.stderr)
            report = run_eval(agent, cases, progress)
            md = report.to_markdown()
            if args.adversarial and args.oracle:
                print("skipping the adversarial run: it needs a real model", file=sys.stderr)
            elif args.adversarial:
                safety = run_adversarial(agent, load_adversarial(DEFAULT_ADVERSARIAL))
                md += "\n" + safety.to_markdown()
            j, m = report.save(args.out)
            m.write_text(md)
            print("\n" + md)
            print(f"saved {j} and {m}")
    finally:
        agent.engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

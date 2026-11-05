"""Run the agent against the golden question set.

Usage:
    python scripts/evaluate.py
    python scripts/evaluate.py --cases evals/golden_questions.json --row-limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from logisql.agent.graph import LogiSQLAgent
from logisql.agent.llm import GroqAnalyticsLLM
from logisql.config import get_settings
from logisql.db.engine import create_engine
from logisql.db.executor import QueryExecutor
from logisql.db.schema import SchemaService
from logisql.db.seed import ensure_demo_database
from logisql.evaluation import CaseResult, evaluate_sql, load_cases

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "evals" / "golden_questions.json"


async def run_evaluation(cases_path: Path, row_limit: int) -> int:
    settings = get_settings()
    if not settings.llm_configured:
        print("GROQ_API_KEY is not configured. Add it to .env before running the evaluation.")
        return 2

    if settings.is_sqlite and settings.allow_demo_seed:
        await asyncio.to_thread(ensure_demo_database, settings)

    engine = create_engine(settings)
    try:
        schema_service = SchemaService(engine=engine, settings=settings)
        executor = QueryExecutor(engine=engine, settings=settings)
        agent = LogiSQLAgent(
            settings=settings,
            schema_service=schema_service,
            executor=executor,
            llm=GroqAnalyticsLLM(settings),
        )

        cases = load_cases(cases_path)
        results: list[CaseResult] = []
        for case in cases:
            response = await agent.run(
                question=case.question,
                request_id=f"eval-{case.id}",
                row_limit=row_limit,
            )
            sql = response.get("sql")
            if response.get("status") != "success":
                result = CaseResult(
                    case.id,
                    False,
                    (f"agent failed: {response.get('error') or 'unknown error'}",),
                )
            else:
                result = evaluate_sql(case, sql)
            results.append(result)

            print(f"[{'PASS' if result.passed else 'FAIL'}] {case.id}")
            for failure in result.failures:
                print(f"       - {failure}")
            print(f"       {' '.join((sql or '').split())[:180]}")

        passed = sum(result.passed for result in results)
        print(f"\n{passed}/{len(results)} golden cases passed")
        return 0 if passed == len(results) else 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate text-to-SQL quality on golden questions.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Path to a golden case JSON file.")
    parser.add_argument("--row-limit", type=int, default=50, help="Row limit passed to the agent.")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_evaluation(args.cases, args.row_limit)))


if __name__ == "__main__":
    main()

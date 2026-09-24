"""Сравнение моделей на русских текстовых задачах: написание, редактура, корректура.

Каждая модель получает одни и те же задания. Оценка двойная:
- автоматическая: объём, запрещённые штампы, исправлены ли заложенные ошибки,
  сколько заложенных ошибок нашла корректура;
- слепая оценка судьёй (по умолчанию claude/opus по подписке): судья не знает,
  какая модель писала, и ставит баллы 1–10 по критериям.

Запуск:
  uv run python scripts/quality_bench.py                       # модели по умолчанию
  uv run python scripts/quality_bench.py -m ccode/gpt-6-sol -m claude/sonnet --runs 2
Отчёт — Markdown в stdout и в файле `--out`.
"""

from __future__ import annotations

import argparse
import re
import statistics
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, Field

from llmkit import LlmKit, Task

DEFAULT_MODELS = [
    "ccode/gpt-5.5",
    "ccode/gpt-5.6-sol",
    "ccode/gpt-5.6-terra",
    "ccode/gpt-5.6-luna",
    "ccode/gpt-6-sol",
    "ccode/gpt-6-astra",
]

# --- задания ---

WRITE_LANDING = """Напиши текст для посадочной страницы услуги «Ремонт стиральных машин на дому в Москве».
Требования:
- 150–200 слов;
- ровно два подзаголовка в формате Markdown `## …`;
- обязательно укажи цену «от 1500 ₽» и срок выезда мастера «в течение 2 часов»;
- без штампов: «индивидуальный подход», «высококвалифицированные специалисты», «широкий спектр услуг»;
- пиши для обычного жителя, конкретно, без воды. Верни только текст."""

WRITE_EXPLAIN = """Объясни новичку, что такое ИНН и зачем он нужен самозанятому.
Требования: 120–180 слов, без канцелярита, один короткий пример из жизни, без списков. Верни только текст."""

EDIT_SOURCE = """В настоящее время наша компания осуществляет деятельность по оказанию услуг по доставке
грузов по всей территории России. Мы доставляем грузы быстро и мы доставляем их надёжно. Наши
водители имеют большой опыт работы, по этому клиенты всегда остаются довольны. Стоимость
доставки расчитывается индивидуально, в зависимости от веса и растояния. Для того чтобы
оформить заказ вам необходимо осуществить звонок по телефону или заполнить заявку на сайте,
после чего менеджер свяжется с Вами в течении часа."""

EDIT_TASK = f"""Отредактируй текст: исправь орфографию и пунктуацию, убери канцелярит и повторы,
сделай текст живым и понятным. Смысл и все факты сохрани. Верни только исправленный текст.

Текст:
{EDIT_SOURCE}"""

# Ошибочные фрагменты, которых не должно остаться после редактуры.
EDIT_MUST_FIX = ["по этому", "расчитывается", "растояния", "в течении", "осуществить звонок"]
# Факты, которые должны сохраниться.
EDIT_MUST_KEEP = ["России", "вес", "час"]

PROOF_SOURCE = """Наша команда проводит аудит сайтов уже больше десяти лет. За это время мы помогли
сотни компаниям выйти в топ поисковой выдачи. Мы тщательно анализируем структуру сайта, скорость
загрузки и качество контента, не смотря на то, что многие конкуренты ограничеваются только
проверкой мета-тегов. Каждый отчёт включает в себя конкретные рекомендации, которые можно
внедрить сразу. Наши клиенты отмечают, что после аудита трафик вырос в среднем в двое.
Если вы хотите узнать, почему ваш сайт не приносит заявок, звоните нам — мы обьясним всё
простым языком. Первая консультация бесплатна, а стоимость аудита зависит от обьёма сайта и
сложности задачь."""

# Заложенные ошибки: ошибочный фрагмент → как должно быть.
PROOF_ERRORS = {
    "сотни компаниям": "сотням компаний",
    "не смотря на то": "несмотря на то",
    "ограничеваются": "ограничиваются",
    "включает в себя": "включает (плеоназм)",
    "в двое": "вдвое",
    "обьясним": "объясним",
    "обьёма": "объёма",
    "задачь": "задач",
}

PROOF_TASK = f"""Ты корректор. Найди в тексте все ошибки: орфографические, грамматические,
пунктуационные и стилистические. Для каждой ошибки укажи точный фрагмент из текста,
тип ошибки и исправление. Не придумывай ошибок, которых нет.

Текст:
{PROOF_SOURCE}"""


class ProofError(BaseModel):
    fragment: str = Field(description="Точный фрагмент из текста с ошибкой")
    kind: str = Field(description="Тип: орфография | грамматика | пунктуация | стиль")
    fix: str = Field(description="Как исправить")


class ProofReport(BaseModel):
    errors: list[ProofError]


class Verdict(BaseModel):
    """Оценка судьи."""

    literacy: int = Field(ge=1, le=10, description="Грамотность: орфография, пунктуация, грамматика")
    style: int = Field(ge=1, le=10, description="Стиль: живость, ясность, отсутствие воды и канцелярита")
    instructions: int = Field(ge=1, le=10, description="Выполнение всех требований задания")
    accuracy: int = Field(ge=1, le=10, description="Точность: факты, сохранение смысла, отсутствие выдумок")
    overall: int = Field(ge=1, le=10, description="Итоговая оценка")
    comment: str = Field(description="Одно-два предложения: главное достоинство и главный недостаток")


TASKS = {
    "write_landing": WRITE_LANDING,
    "write_explain": WRITE_EXPLAIN,
    "edit": EDIT_TASK,
    "proofread": PROOF_TASK,
}

JUDGE_SYSTEM = """Ты строгий редактор русскоязычных текстов. Оцени ответ исполнителя на задание.
Оценивай только результат, будь строг: 10 — безупречно, 7 — хорошо с заметными недочётами,
5 — посредственно, 3 и ниже — плохо. Не знаешь и не угадываешь, какая модель писала."""


def words(text: str) -> int:
    return len(re.findall(r"[\w₽-]+", text))


def auto_checks(task: str, output) -> dict:
    """Проверки без судьи."""
    if task == "proofread":
        found = " ".join(error.fragment.lower() for error in output.errors)
        hits = [fragment for fragment in PROOF_ERRORS if fragment.lower() in found]
        return {"найдено заложенных": f"{len(hits)}/{len(PROOF_ERRORS)}", "всего ошибок в ответе": len(output.errors)}
    text = str(output)
    lower = text.lower()
    if task == "write_landing":
        banned = ["индивидуальный подход", "высококвалифицированн", "широкий спектр"]
        return {
            "слов": words(text),
            "в диапазоне 150–200": 150 <= words(text) <= 200,
            "## ровно 2": len(re.findall(r"^##\s", text, re.M)) == 2,
            "цена и срок": "1500" in text and "2 час" in lower,
            "штампов": sum(phrase in lower for phrase in banned),
        }
    if task == "write_explain":
        return {
            "слов": words(text),
            "в диапазоне 120–180": 120 <= words(text) <= 180,
            "без списков": not re.search(r"^\s*([-*•]|\d+[.)])\s", text, re.M),
        }
    left = [fragment for fragment in EDIT_MUST_FIX if fragment in lower]
    kept = all(fact.lower() in lower for fact in EDIT_MUST_KEEP)
    return {"ошибок осталось": f"{len(left)}/{len(EDIT_MUST_FIX)}", "факты на месте": kept}


def judge_prompt(task: str, output) -> str:
    shown = output.model_dump_json(indent=2) if isinstance(output, BaseModel) else str(output)
    extra = ""
    if task == "proofread":
        listed = "\n".join(f"- «{bad}» → {good}" for bad, good in PROOF_ERRORS.items())
        extra = f"\n\nСправка для судьи — заложенные ошибки (могут быть и другие настоящие):\n{listed}"
    return f"ЗАДАНИЕ:\n{TASKS[task]}\n\nОТВЕТ ИСПОЛНИТЕЛЯ:\n{shown}{extra}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-m", "--model", action="append", help="Модель 'провайдер/модель'; можно несколько.")
    parser.add_argument("--judge", default="claude/opus", help="Модель-судья (по умолчанию claude/opus).")
    parser.add_argument("--runs", type=int, default=1, help="Прогонов каждого задания на модель.")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--out", type=Path, default=Path("quality-report.md"))
    args = parser.parse_args()
    models = args.model or DEFAULT_MODELS

    kit = LlmKit(cache=False, timeout=300, concurrency=args.concurrency, tags={"tool": "quality_bench"})
    jobs = [(model, task, run) for model in models for task in TASKS for run in range(args.runs)]
    answers = kit.ask_many_sync(
        [
            Task(
                user=TASKS[task],
                schema=ProofReport if task == "proofread" else None,
                chain=[model],
                default=None,
                max_tokens=4000,
                id=f"{model}|{task}|{run}",
            )
            for model, task, run in jobs
        ]
    )

    judge_kit = LlmKit(cache=False, timeout=300, concurrency=4, tags={"tool": "quality_bench_judge"})
    done = [(job, answer) for job, answer in zip(jobs, answers, strict=True) if answer.ok]
    verdicts = judge_kit.ask_many_sync(
        [
            Task(system=JUDGE_SYSTEM, user=judge_prompt(task, answer.data), schema=Verdict, chain=[args.judge],
                 default=None, id=f"judge|{model}|{task}|{run}")
            for (model, task, run), answer in done
        ]
    )  # fmt: skip

    lines = [f"# Качество моделей на русских текстах\n\nСудья: `{args.judge}`, прогонов: {args.runs}.\n"]
    scores: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    details = []
    for ((model, task, run), answer), verdict in zip(done, verdicts, strict=True):
        v = verdict.data if verdict.ok else None
        if v is not None:
            scores[model][task].append(v.overall)
        details.append((model, task, run, answer, v))
    failed = [(job, answer) for job, answer in zip(jobs, answers, strict=True) if not answer.ok]

    lines.append("## Итог (средняя оценка судьи, 1–10)\n")
    lines.append("| Модель | " + " | ".join(TASKS) + " | Среднее | Ошибок вызова |")
    lines.append("|---|" + "---|" * (len(TASKS) + 2))
    ranking = []
    for model in models:
        per = [statistics.mean(scores[model][t]) if scores[model][t] else None for t in TASKS]
        known = [p for p in per if p is not None]
        avg = statistics.mean(known) if known else 0
        fails = sum(1 for (m, _, _), _ in failed if m == model)
        ranking.append((avg, model))
        cells = " | ".join(f"{p:.1f}" if p is not None else "—" for p in per)
        lines.append(f"| `{model}` | {cells} | **{avg:.1f}** | {fails} |")

    lines.append("\n## Автоматические проверки\n")
    for model, task, _run, answer, v in details:
        checks = auto_checks(task, answer.data)
        flat = ", ".join(f"{k}: {'да' if val is True else 'нет' if val is False else val}" for k, val in checks.items())
        judge = f"{v.overall}/10 — {v.comment}" if v else "судья не ответил"
        lines.append(
            f"- `{model}` · {task} · {answer.latency_ms / 1000:.0f} с, вход {answer.prompt_tokens} ток. — {flat}. "
            f"Судья: {judge}"
        )
    if failed:
        lines.append("\n## Сбои вызова\n")
        for (model, task, _), answer in failed:
            lines.append(f"- `{model}` · {task}: {(answer.error or '')[:200]}")

    lines.append("\n## Тексты\n")
    for model, task, _run, answer, _ in details:
        body = answer.data.model_dump_json(indent=2) if isinstance(answer.data, BaseModel) else answer.data
        lines.append(f"### `{model}` · {task}\n\n```\n{body}\n```\n")

    report = "\n".join(lines)
    args.out.write_text(report, "utf-8")
    summary = report.split("## Тексты")[0]
    print(summary)
    print(f"Полный отчёт с текстами: {args.out}")


if __name__ == "__main__":
    main()

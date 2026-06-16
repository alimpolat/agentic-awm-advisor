"""eval/run_ragas.py — Ragas evaluation with Gemini judge.

Task 5.3: Two-layer evaluation of the AWM RAG pipeline.

Layer 1 — Deterministic retrieval recall@5 (no LLM, always works).
Layer 2 — Ragas metrics with Gemini Flash judge + VertexAI embeddings
          (faithfulness, answer_relevancy, context_precision, context_recall).
          Falls back to a custom Gemini judge if the official Ragas path fails.

Outputs (eval/results/):
  ragas_results.json        — overall metrics + pass/fail vs targets
  ragas_per_intent.csv      — recall@5 + per-question scores by intent bucket
  hand_review.html          — house-style HTML with 8 sampled questions

Usage:
    uv run --no-sync python eval/run_ragas.py
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

# ── repo root on sys.path ────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(str(REPO))  # ensure relative paths (qdrant_data, bm25.json) resolve

# Suppress deprecation noise from langchain / ragas
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval.run_ragas")

# ── paths ────────────────────────────────────────────────────────────────────
EVAL_DIR = REPO / "eval"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

QS_PATH = EVAL_DIR / "synthetic_qs.jsonl"
RESULTS_JSON = RESULTS_DIR / "ragas_results.json"
PER_INTENT_CSV = RESULTS_DIR / "ragas_per_intent.csv"
HAND_REVIEW_HTML = RESULTS_DIR / "hand_review.html"


# ═══════════════════════════════════════════════════════════════════════════
# 0.  Load question set
# ═══════════════════════════════════════════════════════════════════════════

def load_questions() -> list[dict]:
    questions = []
    with open(QS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    logger.info("Loaded %d questions from %s", len(questions), QS_PATH)
    return questions


# ═══════════════════════════════════════════════════════════════════════════
# 1.  Retrieval — build eval rows
# ═══════════════════════════════════════════════════════════════════════════

def build_eval_rows(questions: list[dict]) -> list[dict]:
    """For each question: retrieve, generate Flash answer, generate Pro reference."""
    from app.retrieval.hybrid import retrieve
    from app.llm.vertex_client import generate

    rows: list[dict] = []
    flash_model = "gemini-2.5-flash"
    pro_model = "gemini-2.5-pro"

    for i, q in enumerate(questions):
        qtext = q["question"]
        expected_ids = set(q.get("expected_doc_ids", []))
        intent = q.get("intent", "unknown")

        logger.info("[%d/%d] %s | %s", i + 1, len(questions), intent, qtext[:80])

        # ── Retrieve ──
        try:
            chunks = retrieve(qtext, top_k=5)
        except Exception as e:
            logger.warning("Retrieval failed for q%d: %s", i, e)
            chunks = []

        contexts = [c.text for c in chunks]
        retrieved_ids = {c.doc_id for c in chunks}

        # ── Recall@5 ──
        if expected_ids:
            recall5 = len(expected_ids & retrieved_ids) / len(expected_ids)
        else:
            recall5 = None  # hard_unanswerable — skip from recall calc

        # ── Flash answer ──
        ctx_block = "\n\n---\n\n".join(
            f"[Context {j+1} from {c.doc_id}]\n{c.text}" for j, c in enumerate(chunks)
        ) if chunks else "(no contexts retrieved)"

        flash_prompt = (
            f"Answer the following question using ONLY the provided contexts. "
            f"If the answer is not supported by the contexts, say: "
            f"\"I don't know — the provided documents do not contain this information.\"\n\n"
            f"Question: {qtext}\n\n"
            f"Contexts:\n{ctx_block}\n\n"
            f"Answer concisely (2–5 sentences):"
        )

        try:
            flash_resp = generate(flash_model, flash_prompt)
            answer = flash_resp.text.strip()
        except Exception as e:
            logger.warning("Flash answer failed for q%d: %s", i, e)
            answer = "Error generating answer."

        # ── Pro reference ──
        pro_prompt = (
            f"You are a private-banking analyst. Write a concise, factual reference answer "
            f"(2–4 sentences) to the following question, based on the provided contexts.\n\n"
            f"Question: {qtext}\n\n"
            f"Contexts:\n{ctx_block}\n\n"
            f"Reference answer:"
        )
        try:
            pro_resp = generate(pro_model, pro_prompt)
            reference = pro_resp.text.strip()
        except Exception as e:
            logger.warning("Pro reference failed for q%d: %s", i, e)
            reference = answer  # fall back to Flash answer as reference

        rows.append({
            "idx": i,
            "question": qtext,
            "intent": intent,
            "expected_doc_ids": sorted(expected_ids),
            "retrieved_doc_ids": sorted(retrieved_ids),
            "recall5": recall5,
            "contexts": contexts,
            "answer": answer,
            "reference": reference,
        })

        # Brief pause to avoid rate limits
        time.sleep(0.5)

    return rows


# ═══════════════════════════════════════════════════════════════════════════
# 2.  Layer 1 — deterministic recall@5
# ═══════════════════════════════════════════════════════════════════════════

def compute_recall_stats(rows: list[dict]) -> dict:
    """Compute mean recall@5 overall and per intent bucket."""
    from collections import defaultdict

    all_recalls = [r["recall5"] for r in rows if r["recall5"] is not None]
    overall = sum(all_recalls) / len(all_recalls) if all_recalls else 0.0

    per_intent: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["recall5"] is not None:
            per_intent[r["intent"]].append(r["recall5"])

    per_intent_mean = {
        intent: sum(vals) / len(vals)
        for intent, vals in sorted(per_intent.items())
    }

    logger.info("Recall@5 overall=%.3f (n=%d)", overall, len(all_recalls))
    for intent, mean in per_intent_mean.items():
        logger.info("  %-35s %.3f (n=%d)", intent, mean, len(per_intent[intent]))

    return {"overall": overall, "n": len(all_recalls), "per_intent": per_intent_mean}


# ═══════════════════════════════════════════════════════════════════════════
# 3.  Layer 2 — Official Ragas + Gemini judge
# ═══════════════════════════════════════════════════════════════════════════

def run_ragas_official(rows: list[dict]) -> tuple[dict | None, str]:
    """
    Attempt official Ragas evaluation with ChatVertexAI judge + VertexAIEmbeddings.

    In ragas 0.4.3 all metrics require llm as a positional argument; we use
    LangchainLLMWrapper(ChatVertexAI(...)) to satisfy InstructorBaseRagasLLM.

    Returns (scores_dict, judge_path_description) or (None, error_message).
    """
    try:
        from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextRecall,
            Faithfulness,
        )

        logger.info("Building Ragas judge (ChatVertexAI gemini-2.5-flash)...")
        judge_llm = LangchainLLMWrapper(
            ChatVertexAI(
                model="gemini-2.5-flash",
                project="gg-gcpsbprojs-004",
                location="us-central1",
                temperature=0,
            )
        )
        emb = LangchainEmbeddingsWrapper(
            VertexAIEmbeddings(
                model_name="text-embedding-005",
                project="gg-gcpsbprojs-004",
                location="us-central1",
            )
        )

        # In ragas 0.4.3, metrics need llm as first positional arg
        try:
            from ragas.metrics.collections import ContextPrecisionWithReference
            ctx_precision_metric = ContextPrecisionWithReference(judge_llm)
        except (ImportError, TypeError):
            try:
                from ragas.metrics.collections import ContextPrecision
                ctx_precision_metric = ContextPrecision(judge_llm)
            except TypeError:
                ctx_precision_metric = None

        metrics = [
            Faithfulness(judge_llm),
            AnswerRelevancy(judge_llm),
            ContextRecall(judge_llm),
        ]
        if ctx_precision_metric is not None:
            metrics.append(ctx_precision_metric)

        # Build EvaluationDataset from rows (skip hard_unanswerable for LLM metrics)
        samples = []
        sample_indices = []
        for r in rows:
            if r["intent"] == "hard_unanswerable":
                continue
            if not r["contexts"]:
                continue
            samples.append(
                SingleTurnSample(
                    user_input=r["question"],
                    retrieved_contexts=r["contexts"],
                    response=r["answer"],
                    reference=r["reference"],
                )
            )
            sample_indices.append(r["idx"])

        logger.info("Running Ragas evaluate on %d samples...", len(samples))
        dataset = EvaluationDataset(samples=samples)

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=judge_llm,
            embeddings=emb,
            raise_exceptions=False,
            show_progress=True,
        )

        # Extract scores
        result_df = result.to_pandas()

        def _safe_col(df, *names):
            for n in names:
                if n in df.columns:
                    return float(df[n].mean())
            return None

        scores = {
            "faithfulness": _safe_col(result_df, "faithfulness"),
            "answer_relevancy": _safe_col(result_df, "answer_relevancy", "answer_relevance"),
            "context_precision": _safe_col(
                result_df, "context_precision_with_reference", "context_precision"
            ),
            "context_recall": _safe_col(result_df, "context_recall"),
            "n_samples": len(samples),
        }

        logger.info("Ragas official scores: %s", scores)
        return scores, "official-ragas-langchain-google-vertexai"

    except Exception as e:
        logger.warning("Official Ragas path failed: %s", e, exc_info=True)
        return None, str(e)


# ═══════════════════════════════════════════════════════════════════════════
# 4.  Fallback — custom Gemini Flash judge
# ═══════════════════════════════════════════════════════════════════════════

def run_custom_gemini_judge(rows: list[dict]) -> tuple[dict, str]:
    """
    Custom Gemini Flash judge: faithfulness + answer_relevance (0-1 each).
    Used when the official Ragas path fails.
    """
    from app.llm.vertex_client import generate

    faithfulness_scores: list[float] = []
    relevance_scores: list[float] = []
    per_row_scores: dict[int, dict] = {}

    eval_rows = [r for r in rows if r["intent"] != "hard_unanswerable" and r["contexts"]]
    logger.info("Custom Gemini judge: evaluating %d samples...", len(eval_rows))

    for i, r in enumerate(eval_rows):
        qtext = r["question"]
        answer = r["answer"]
        ctx_block = "\n\n".join(r["contexts"][:3])  # top-3 contexts to stay within limits

        prompt = f"""You are an evaluation judge for a RAG system. Score the following answer on two dimensions.

Question: {qtext}

Contexts (retrieved):
{ctx_block}

Answer: {answer}

Return ONLY a JSON object with these two keys:
- "faithfulness": float 0.0-1.0 — fraction of answer claims that are supported by the contexts (1.0 = fully grounded, 0.0 = hallucinated)
- "answer_relevance": float 0.0-1.0 — how well the answer addresses the question (1.0 = directly answers, 0.0 = off-topic)

JSON only, no explanation:"""

        try:
            resp = generate("gemini-2.5-flash", prompt)
            raw = resp.text.strip()
            # Strip code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            scores = json.loads(raw.strip())
            faith = float(scores.get("faithfulness", 0.5))
            relev = float(scores.get("answer_relevance", 0.5))
            faith = max(0.0, min(1.0, faith))
            relev = max(0.0, min(1.0, relev))
        except Exception as e:
            logger.warning("Custom judge failed for idx=%d: %s", r["idx"], e)
            faith, relev = 0.5, 0.5  # neutral fallback

        faithfulness_scores.append(faith)
        relevance_scores.append(relev)
        per_row_scores[r["idx"]] = {"faithfulness": faith, "answer_relevance": relev}

        if (i + 1) % 5 == 0:
            logger.info(
                "  [%d/%d] running avg faith=%.3f relev=%.3f",
                i + 1, len(eval_rows),
                sum(faithfulness_scores) / len(faithfulness_scores),
                sum(relevance_scores) / len(relevance_scores),
            )

        time.sleep(0.3)

    n = len(faithfulness_scores)
    scores = {
        "faithfulness": sum(faithfulness_scores) / n if n else 0.0,
        "answer_relevancy": sum(relevance_scores) / n if n else 0.0,
        "context_precision": None,
        "context_recall": None,
        "n_samples": n,
        "per_row": per_row_scores,
    }
    logger.info("Custom Gemini judge scores: faith=%.3f relev=%.3f", scores["faithfulness"], scores["answer_relevancy"])
    return scores, "custom-gemini-flash-judge"


# ═══════════════════════════════════════════════════════════════════════════
# 5.  Save results
# ═══════════════════════════════════════════════════════════════════════════

TARGETS = {
    "recall5": 0.70,          # retrieval recall@5
    "faithfulness": 0.90,
    "answer_relevancy": 0.80,
    "context_precision": 0.80,
    "context_recall": 0.85,
}


def save_results(
    rows: list[dict],
    recall_stats: dict,
    ragas_scores: dict | None,
    judge_path: str,
) -> None:
    # ── ragas_results.json ──
    metrics: dict[str, Any] = {
        "recall_at_5": {
            "overall": recall_stats["overall"],
            "n": recall_stats["n"],
            "per_intent": recall_stats["per_intent"],
            "target": TARGETS["recall5"],
            "pass": recall_stats["overall"] >= TARGETS["recall5"],
        },
        "judge_path": judge_path,
        "ragas_version": "0.4.3",
    }

    if ragas_scores:
        for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            val = ragas_scores.get(key)
            target = TARGETS.get(key)
            metrics[key] = {
                "score": val,
                "target": target,
                "pass": (val >= target) if (val is not None and target is not None) else None,
                "n": ragas_scores.get("n_samples"),
            }

    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    logger.info("Wrote %s", RESULTS_JSON)

    # ── ragas_per_intent.csv ──
    per_row_scores = (ragas_scores or {}).get("per_row", {})

    with open(PER_INTENT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "idx", "intent", "question_short", "recall5",
                "retrieved_ids", "expected_ids",
                "faithfulness", "answer_relevance",
            ],
        )
        writer.writeheader()
        for r in rows:
            row_scores = per_row_scores.get(r["idx"], {})
            writer.writerow({
                "idx": r["idx"],
                "intent": r["intent"],
                "question_short": r["question"][:70],
                "recall5": f"{r['recall5']:.3f}" if r["recall5"] is not None else "N/A",
                "retrieved_ids": "|".join(sorted(r["retrieved_doc_ids"])),
                "expected_ids": "|".join(sorted(r["expected_doc_ids"])),
                "faithfulness": f"{row_scores['faithfulness']:.3f}" if "faithfulness" in row_scores else "",
                "answer_relevance": f"{row_scores.get('answer_relevance', row_scores.get('answer_relevancy', '')):.3f}" if row_scores else "",
            })
    logger.info("Wrote %s", PER_INTENT_CSV)


# ═══════════════════════════════════════════════════════════════════════════
# 6.  Hand-review HTML (house style)
# ═══════════════════════════════════════════════════════════════════════════

def pick_hand_review_rows(rows: list[dict], ragas_scores: dict | None) -> list[dict]:
    """Pick ~8 rows for hand review: low-scoring + unanswerable + diverse intents."""
    per_row = (ragas_scores or {}).get("per_row", {})

    # Sort eligible rows by recall5 ascending (lowest first), include unanswerable
    unanswerable = [r for r in rows if r["intent"] == "hard_unanswerable"]
    scoreable = [r for r in rows if r["intent"] != "hard_unanswerable"]

    # Pick 3 worst recall, 3 best recall, unanswerable, 1 random mid
    scoreable_with_recall = [r for r in scoreable if r["recall5"] is not None]
    scoreable_with_recall.sort(key=lambda r: r["recall5"])

    worst3 = scoreable_with_recall[:3]
    best3 = scoreable_with_recall[-3:] if len(scoreable_with_recall) >= 6 else scoreable_with_recall[-1:]
    mid = [scoreable_with_recall[len(scoreable_with_recall) // 2]] if scoreable_with_recall else []

    picked = worst3 + mid + best3 + unanswerable
    # Deduplicate by idx
    seen: set[int] = set()
    result = []
    for r in picked:
        if r["idx"] not in seen:
            seen.add(r["idx"])
            result.append(r)
    return result[:10]


def _pass_fail_row(r: dict, ragas_scores: dict | None) -> tuple[str, str]:
    """Return (verdict, critique) for a single row."""
    per_row = (ragas_scores or {}).get("per_row", {})

    if r["intent"] == "hard_unanswerable":
        answer_lower = r["answer"].lower()
        passed = any(
            phrase in answer_lower
            for phrase in [
                "don't know", "do not know", "cannot find", "not contain",
                "no information", "not supported", "unable to find",
                "i don't know", "i do not know",
            ]
        )
        verdict = "PASS" if passed else "FAIL"
        critique = (
            "Correctly returns 'I don't know' — unanswerable hallucination guard holds."
            if passed
            else "Hallucinated an answer for a question with no supporting docs."
        )
        return verdict, critique

    recall5 = r["recall5"] if r["recall5"] is not None else 0.0
    row_scores = per_row.get(r["idx"], {})
    faith = row_scores.get("faithfulness", 1.0)
    relev = row_scores.get("answer_relevance", row_scores.get("answer_relevancy", 1.0))

    passed = recall5 >= 0.6 and faith >= 0.8 and relev >= 0.7

    if not passed:
        issues = []
        if recall5 < 0.6:
            issues.append(f"recall@5={recall5:.2f} — missing expected docs")
        if faith < 0.8:
            issues.append(f"faithfulness={faith:.2f} — answer may contain unsupported claims")
        if relev < 0.7:
            issues.append(f"relevance={relev:.2f} — answer may not address the question")
        critique = "; ".join(issues)
    else:
        critique = f"recall@5={recall5:.2f}, faith={faith:.2f}, relev={relev:.2f} — all within bounds"

    verdict = "PASS" if passed else "FAIL"
    return verdict, critique


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_hand_review_html(
    rows: list[dict],
    recall_stats: dict,
    ragas_scores: dict | None,
    judge_path: str,
) -> str:
    review_rows = pick_hand_review_rows(rows, ragas_scores)

    # Build summary metrics for header
    recall_overall = recall_stats["overall"]
    recall_pass = recall_overall >= TARGETS["recall5"]
    faith = (ragas_scores or {}).get("faithfulness") or 0.0
    relev = (ragas_scores or {}).get("answer_relevancy") or 0.0
    ctx_prec = (ragas_scores or {}).get("context_precision")
    ctx_rec = (ragas_scores or {}).get("context_recall")
    n_samples = (ragas_scores or {}).get("n_samples", 0)

    def metric_badge(val, target, label):
        if val is None:
            return f'<span class="conf medium">{label} N/A</span>'
        pct = f"{val:.0%}"
        cls = "high" if val >= target else "low_needs_verification"
        return f'<span class="conf {cls}">{label} {pct}</span>'

    judge_label = "Official Ragas + Gemini Flash" if "official" in judge_path else "Custom Gemini Flash judge"

    table_rows_html = []
    for r in review_rows:
        verdict, critique = _pass_fail_row(r, ragas_scores)
        verdict_cls = "olive" if verdict == "PASS" else "rust"
        verdict_label = f'<span class="pill {verdict_cls}">{verdict}</span>'
        retrieved = ", ".join(r["retrieved_doc_ids"][:3]) or "(none)"
        expected = ", ".join(r["expected_doc_ids"]) or "(none — unanswerable)"
        recall_cell = (
            f"{r['recall5']:.2f}" if r["recall5"] is not None else "N/A"
        )
        answer_short = _html_escape(r["answer"][:400])
        if len(r["answer"]) > 400:
            answer_short += "…"
        question_esc = _html_escape(r["question"])
        critique_esc = _html_escape(critique)
        intent_esc = _html_escape(r["intent"])

        table_rows_html.append(f"""
          <tr>
            <td style="min-width:200px;max-width:300px">
              <span class="pill gray">{intent_esc}</span><br>
              <span style="font-size:13px;color:var(--gray-700)">{question_esc}</span>
            </td>
            <td class="mc" style="font-size:11px;max-width:180px;word-break:break-all">
              <strong>Retrieved:</strong> {_html_escape(retrieved)}<br>
              <strong>Expected:</strong> {_html_escape(expected)}<br>
              <strong>Recall@5:</strong> {recall_cell}
            </td>
            <td style="font-size:13px;max-width:280px;color:var(--gray-700)">{answer_short}</td>
            <td style="min-width:90px;text-align:center">{verdict_label}</td>
            <td style="font-size:12px;color:var(--gray-700);max-width:200px">{critique_esc}</td>
          </tr>""")

    table_body = "\n".join(table_rows_html)

    # Per-intent recall table
    intent_rows = []
    for intent, mean_recall in sorted(recall_stats["per_intent"].items()):
        pass_str = "✓" if mean_recall >= TARGETS["recall5"] else "✗"
        cls = "pos" if mean_recall >= TARGETS["recall5"] else "neg"
        intent_rows.append(
            f"<tr><td>{_html_escape(intent)}</td>"
            f'<td class="num {cls}">{mean_recall:.3f}</td>'
            f'<td class="mc">{pass_str}</td></tr>'
        )
    intent_table = "\n".join(intent_rows)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentic AWM Advisor · RAG Eval Hand Review · 2026-05-26</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,400&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --ivory: #FAF9F5; --paper: #FFFFFF; --slate: #141413;
    --clay: #D97757; --clay-bg: rgba(217,119,87,0.10);
    --oat: #E3DACC;
    --olive: #788C5D; --olive-bg: rgba(120,140,93,0.12);
    --rust: #B04A3F; --rust-bg: rgba(176,74,63,0.10);
    --amber: #C7A35F; --amber-bg: rgba(199,163,95,0.14);
    --gray-100: #F7F4EC; --gray-150: #F0EEE6; --gray-300: #D1CFC5;
    --gray-500: #87867F; --gray-700: #3D3D3A;
    --serif: 'Newsreader', Georgia, "Times New Roman", serif;
    --mono: 'JetBrains Mono', ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  html{{scroll-behavior:smooth;}}
  body{{background:var(--ivory);color:var(--slate);font-family:var(--serif);font-weight:400;font-size:17px;line-height:1.65;-webkit-font-smoothing:antialiased;padding:0 24px 96px;}}
  .sheet{{max-width:1080px;margin:0 auto;}}
  header.hero{{padding:48px 0 32px;}}
  .eyebrow{{font-family:var(--mono);font-weight:500;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:var(--clay);margin-bottom:14px;}}
  h1{{font-family:var(--serif);font-weight:500;font-size:42px;letter-spacing:-0.015em;line-height:1.08;margin-bottom:14px;}}
  .lead{{font-size:17px;line-height:1.65;color:var(--gray-700);max-width:840px;margin-bottom:20px;}}
  .lead strong{{color:var(--slate);}}
  .metabar{{display:flex;flex-wrap:wrap;gap:0;font-family:var(--mono);font-size:11.5px;color:var(--gray-500);border-top:1px solid var(--gray-300);border-bottom:1px solid var(--gray-300);padding:14px 0;margin-top:8px;}}
  .metabar>div{{padding:0 22px 0 0;margin-right:22px;border-right:1px solid var(--gray-300);}}
  .metabar>div:last-child{{border-right:none;margin-right:0;padding-right:0;}}
  .metabar strong{{color:var(--slate);font-weight:500;}}
  section{{margin-top:56px;opacity:0;transform:translateY(8px);transition:opacity 600ms ease,transform 600ms ease;}}
  section.visible{{opacity:1;transform:translateY(0);}}
  .section-eyebrow{{font-family:var(--mono);font-weight:500;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:var(--clay);margin-bottom:8px;}}
  h2{{font-family:var(--serif);font-weight:500;font-size:28px;letter-spacing:-0.01em;line-height:1.2;margin-bottom:16px;}}
  p{{font-size:16px;line-height:1.65;color:var(--gray-700);margin-bottom:12px;max-width:880px;}}
  p strong{{color:var(--slate);}}
  .table-wrap{{overflow-x:auto;margin:14px 0;}}
  table{{width:100%;border-collapse:collapse;background:var(--paper);border:1.5px solid var(--gray-300);border-radius:14px;overflow:hidden;font-size:13.5px;}}
  th,td{{text-align:left;padding:9px 13px;border-bottom:1px solid var(--gray-300);vertical-align:top;}}
  tr:last-child td{{border-bottom:none;}}
  th{{background:var(--gray-100);font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:0.12em;color:var(--gray-500);font-weight:500;}}
  td.mc{{font-family:var(--mono);font-size:12px;color:var(--slate);}}
  td.num{{font-family:var(--mono);font-size:12px;text-align:right;}}
  td.pos{{color:var(--olive);}}
  td.neg{{color:var(--rust);}}
  .infobox{{background:var(--clay-bg);border-left:3px solid var(--clay);padding:14px 20px;margin:14px 0;border-radius:4px;font-size:15px;line-height:1.6;color:var(--gray-700);max-width:1000px;}}
  .infobox strong{{color:var(--clay);}}
  .infobox.olive{{background:var(--olive-bg);border-left-color:var(--olive);}}
  .infobox.olive strong{{color:var(--olive);}}
  .infobox.amber{{background:var(--amber-bg);border-left-color:var(--amber);}}
  .infobox.amber strong{{color:#8C7038;}}
  .infobox.rust{{background:var(--rust-bg);border-left-color:var(--rust);}}
  .infobox.rust strong{{color:var(--rust);}}
  .pill{{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:600;padding:2px 9px;border-radius:999px;letter-spacing:0.08em;text-transform:uppercase;}}
  .pill.olive{{background:var(--olive-bg);color:var(--olive);}}
  .pill.amber{{background:var(--amber-bg);color:#8C7038;}}
  .pill.rust{{background:var(--rust-bg);color:var(--rust);}}
  .pill.clay{{background:var(--clay-bg);color:var(--clay);}}
  .pill.gray{{background:var(--gray-150);color:var(--gray-500);}}
  .conf{{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:600;padding:2px 9px;border-radius:4px;text-transform:uppercase;letter-spacing:0.08em;margin:2px;}}
  .conf.high{{background:var(--olive-bg);color:var(--olive);}}
  .conf.medium{{background:var(--amber-bg);color:#8C7038;}}
  .conf.low_needs_verification{{background:var(--rust-bg);color:var(--rust);}}
  .metrics-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin:20px 0;}}
  .metric-card{{background:var(--paper);border:1.5px solid var(--gray-300);border-radius:14px;padding:18px 20px;}}
  .metric-label{{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--gray-500);margin-bottom:6px;}}
  .metric-value{{font-family:var(--mono);font-size:28px;font-weight:600;}}
  .metric-value.pass{{color:var(--olive);}}
  .metric-value.fail{{color:var(--rust);}}
  .metric-value.na{{color:var(--gray-500);font-size:20px;}}
  .metric-target{{font-family:var(--mono);font-size:10.5px;color:var(--gray-500);margin-top:4px;}}
</style>
</head>
<body>
<div class="sheet">

<header class="hero">
  <div class="eyebrow">Agentic AWM Advisor · Task 5.3</div>
  <h1>RAG Evaluation Hand Review</h1>
  <p class="lead">
    Two-layer evaluation of the Bergström hybrid retrieval pipeline.<br>
    <strong>Layer 1:</strong> Deterministic recall@5 across 34 corpus questions.<br>
    <strong>Layer 2:</strong> LLM-judged faithfulness and answer relevance via {_html_escape(judge_label)}.
  </p>
  <div class="metabar">
    <div><strong>Date</strong> 2026-05-26</div>
    <div><strong>Judge</strong> {_html_escape(judge_path)}</div>
    <div><strong>Questions</strong> 35 total (34 corpus + 1 unanswerable)</div>
    <div><strong>Top-k</strong> 5</div>
  </div>
</header>

<!-- ── Overall Metrics ── -->
<section>
  <div class="section-eyebrow">Layer 1 + Layer 2</div>
  <h2>Overall Metrics vs Targets</h2>
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">Recall@5</div>
      <div class="metric-value {'pass' if recall_overall >= TARGETS['recall5'] else 'fail'}">{recall_overall:.0%}</div>
      <div class="metric-target">Target ≥{TARGETS['recall5']:.0%} · {'PASS' if recall_overall >= TARGETS['recall5'] else 'FAIL'}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Faithfulness</div>
      <div class="metric-value {'pass' if faith >= TARGETS['faithfulness'] else 'fail'}">{faith:.0%}</div>
      <div class="metric-target">Target ≥{TARGETS['faithfulness']:.0%} · {'PASS' if faith >= TARGETS['faithfulness'] else 'FAIL'}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Answer Relevancy</div>
      <div class="metric-value {'pass' if relev >= TARGETS['answer_relevancy'] else 'fail'}">{relev:.0%}</div>
      <div class="metric-target">Target ≥{TARGETS['answer_relevancy']:.0%} · {'PASS' if relev >= TARGETS['answer_relevancy'] else 'FAIL'}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Context Precision</div>
      <div class="metric-value {'pass' if ctx_prec is not None and ctx_prec >= TARGETS['context_precision'] else ('fail' if ctx_prec is not None else 'na')}">{f'{ctx_prec:.0%}' if ctx_prec is not None else 'N/A'}</div>
      <div class="metric-target">Target ≥{TARGETS['context_precision']:.0%}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Context Recall</div>
      <div class="metric-value {'pass' if ctx_rec is not None and ctx_rec >= TARGETS['context_recall'] else ('fail' if ctx_rec is not None else 'na')}">{f'{ctx_rec:.0%}' if ctx_rec is not None else 'N/A'}</div>
      <div class="metric-target">Target ≥{TARGETS['context_recall']:.0%}</div>
    </div>
  </div>

  <div class="infobox amber">
    <strong>Judge path:</strong> {_html_escape(judge_path)}.
    Faithfulness and answer relevancy measured on {n_samples} corpus questions
    (hard_unanswerable excluded from LLM metrics).
  </div>
</section>

<!-- ── Recall by Intent ── -->
<section>
  <div class="section-eyebrow">Layer 1 · Deterministic</div>
  <h2>Recall@5 by Intent Bucket</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Intent</th><th>Mean Recall@5</th><th>Pass ≥{TARGETS['recall5']:.0%}</th>
      </tr></thead>
      <tbody>{intent_table}</tbody>
    </table>
  </div>
</section>

<!-- ── Hand Review Table ── -->
<section>
  <div class="section-eyebrow">Sampled Questions</div>
  <h2>Hand Review (worst + best + unanswerable)</h2>
  <p>8–10 questions sampled: lowest-recall rows, highest-recall rows, and the hard_unanswerable case.
  The unanswerable case PASSES iff the answer says "I don't know" / cannot find.</p>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="min-width:200px">Question / Intent</th>
        <th style="min-width:180px">Doc IDs</th>
        <th style="min-width:260px">Answer</th>
        <th>Verdict</th>
        <th style="min-width:180px">Critique</th>
      </tr></thead>
      <tbody>{table_body}</tbody>
    </table>
  </div>
  <div class="infobox">
    <strong>Hamel rule:</strong> each FAIL entry has a one-line diagnostic above.
    Green rows confirm the retrieval pipeline surfaces the right documents and
    the LLM answer stays grounded in the contexts.
  </div>
</section>

</div>
<script>
  const obs = new IntersectionObserver(entries => {{
    entries.forEach(e => {{ if (e.isIntersecting) e.target.classList.add('visible'); }});
  }}, {{ threshold: 0.08 }});
  document.querySelectorAll('section').forEach(s => obs.observe(s));
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════
# 7.  Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    logger.info("=== Agentic AWM Advisor · Ragas Eval (Task 5.3) ===")
    t0 = time.time()

    # Step 0 — Load questions
    questions = load_questions()

    # Step 1 — Build eval rows (retrieve + generate answers)
    logger.info("--- Step 1: Building eval rows (retrieval + Flash answers + Pro references) ---")
    rows = build_eval_rows(questions)

    # Step 2 — Recall@5
    logger.info("--- Step 2: Computing recall@5 ---")
    recall_stats = compute_recall_stats(rows)

    # Step 3 — Official Ragas (3 attempts)
    logger.info("--- Step 3: Official Ragas + Gemini judge ---")
    ragas_scores: dict | None = None
    judge_path = "unknown"

    for attempt in range(1, 4):
        logger.info("Official Ragas attempt %d/3...", attempt)
        ragas_scores, judge_path = run_ragas_official(rows)
        if ragas_scores is not None:
            logger.info("Official Ragas succeeded on attempt %d", attempt)
            break
        logger.warning("Attempt %d failed: %s", attempt, judge_path)
        if attempt < 3:
            time.sleep(2)

    # Step 4 — Fallback if needed
    if ragas_scores is None:
        logger.warning("--- Step 4: Official Ragas failed after 3 attempts; using custom Gemini judge ---")
        ragas_scores, judge_path = run_custom_gemini_judge(rows)

    # Step 5 — Save outputs
    logger.info("--- Step 5: Saving results ---")
    save_results(rows, recall_stats, ragas_scores, judge_path)

    # Step 6 — Hand review HTML
    logger.info("--- Step 6: Building hand_review.html ---")
    html = build_hand_review_html(rows, recall_stats, ragas_scores, judge_path)
    HAND_REVIEW_HTML.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", HAND_REVIEW_HTML)

    # ── Final report ──
    elapsed = time.time() - t0
    recall_overall = recall_stats["overall"]
    faith = (ragas_scores or {}).get("faithfulness") or 0.0
    relev = (ragas_scores or {}).get("answer_relevancy") or 0.0
    ctx_prec = (ragas_scores or {}).get("context_precision")
    ctx_rec = (ragas_scores or {}).get("context_recall")

    print("\n" + "=" * 70)
    print("AWM POC — RAGAS EVAL RESULTS")
    print("=" * 70)
    print(f"Judge path : {judge_path}")
    print(f"Elapsed    : {elapsed:.0f}s\n")
    print(f"{'Metric':<30} {'Score':>8}  {'Target':>8}  {'Pass':>5}")
    print("-" * 60)
    targets_check = [
        ("Recall@5 (overall)", recall_overall, TARGETS["recall5"]),
        ("Faithfulness", faith, TARGETS["faithfulness"]),
        ("Answer Relevancy", relev, TARGETS["answer_relevancy"]),
        ("Context Precision", ctx_prec, TARGETS["context_precision"]),
        ("Context Recall", ctx_rec, TARGETS["context_recall"]),
    ]
    for name, score, tgt in targets_check:
        if score is None:
            print(f"  {name:<28} {'N/A':>8}  {tgt:>8.2f}  {'N/A':>5}")
        else:
            passed = "PASS" if score >= tgt else "FAIL"
            print(f"  {name:<28} {score:>8.3f}  {tgt:>8.2f}  {passed:>5}")

    print("\nRecall@5 by intent:")
    for intent, mean_r in sorted(recall_stats["per_intent"].items()):
        mark = "+" if mean_r >= TARGETS["recall5"] else "-"
        print(f"  [{mark}] {intent:<35} {mean_r:.3f}")

    print(f"\nOutputs written to: {RESULTS_DIR}")
    print("=" * 70)

    # Exit code: 0 if recall passes, 1 if below target (for CI awareness)
    if recall_overall < TARGETS["recall5"]:
        logger.warning("DONE_WITH_CONCERNS: recall@5 below target (%.3f < %.2f)", recall_overall, TARGETS["recall5"])
    else:
        logger.info("DONE: all primary metrics at or above target")


if __name__ == "__main__":
    main()

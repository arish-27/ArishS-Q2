"""
End-to-end RAG evaluation script (20 in-knowledge Q&A + 5 out-of-knowledge hallucination checks).
Runs inside the backend container against real retrieval (pgvector) and Gemini LLM.

Usage:
  docker compose exec backend python scripts/eval_rag.py
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.providers.llm.base import LLMRateLimitError
from app.providers.llm.gemini_provider import GeminiProvider
from app.services.rag_service import retrieve_relevant_chunks

API_BASE = "http://127.0.0.1:8000/api/v1"
DOCS_EVAL_DIR = Path("/app/docs/eval")
if not DOCS_EVAL_DIR.exists():
    DOCS_EVAL_DIR = Path(__file__).resolve().parents[2] / "docs" / "eval"


def _http_json(url: str, method: str = "GET", data: Any = None, token: str = "") -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _upload_file(url: str, agent_id: str, file_path: Path, token: str) -> Dict[str, Any]:
    boundary = "----EvalBoundary7MA4YWxkTrZu0gW"
    content = file_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="agent_id"\r\n\r\n{agent_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round((pct / 100.0) * (len(s) - 1)))))
    return round(s[idx], 1)


async def judge_answer(llm: GeminiProvider, question: str, expected_kw: List[str], answer: str) -> float:
    prompt = (
        "Score how well the Assistant Answer answers the Question based on the Expected Keywords.\n"
        "Return ONLY a single decimal number between 0.0 and 1.0 (e.g. 1.0, 0.5, 0.0).\n\n"
        f"Question: {question}\n"
        f"Expected Keywords: {expected_kw}\n"
        f"Assistant Answer: {answer}\n"
        "Score:"
    )
    for attempt in range(4):
        try:
            raw = await llm.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You are a strict grading judge. Output only a float between 0.0 and 1.0.",
                temperature=0.0,
                model=settings.DEFAULT_GEMINI_MODEL,
            )
            for token in raw.replace(",", " ").split():
                try:
                    val = float(token)
                    return max(0.0, min(1.0, val))
                except ValueError:
                    continue
            return 0.0
        except LLMRateLimitError:
            await asyncio.sleep(12.0)
        except Exception:
            return 0.0
    return 0.0


async def main() -> None:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY must be configured to run eval_rag.py")

    handbook_path = DOCS_EVAL_DIR / "company_handbook.txt"
    qa_path = DOCS_EVAL_DIR / "qa_pairs.json"
    qa_data = json.loads(qa_path.read_text(encoding="utf-8"))

    email = f"eval_{uuid.uuid4().hex[:8]}@example.com"
    reg = _http_json(f"{API_BASE}/auth/register", "POST", {"email": email, "password": "Password123!"})
    token = reg["access_token"]

    agent = _http_json(
        f"{API_BASE}/agents",
        "POST",
        {
            "name": "AetherGrid Eval Agent",
            "system_prompt": (
                "You are a factual assistant for AetherGrid Robotics. "
                "Answer ONLY using the provided [Knowledge Base Context]. "
                "If the answer is not in the context, say clearly: 'I do not have that information in my knowledge base.'"
            ),
            "llm_provider": "gemini",
            "llm_model": settings.DEFAULT_GEMINI_MODEL,
            "temperature": 0.1,
        },
        token=token,
    )
    agent_id = agent["id"]

    doc = _upload_file(f"{API_BASE}/knowledge/upload", agent_id, handbook_path, token)
    doc_id = doc["id"]

    # Poll until indexed
    for _ in range(60):
        docs = _http_json(f"{API_BASE}/knowledge?agent_id={agent_id}", "GET", token=token)
        match = next((d for d in docs if d["id"] == doc_id), None)
        if match and match["status"] == "indexed":
            print(f"Indexed document {doc_id} ({match['chunk_count']} chunks)")
            break
        if match and match["status"] == "failed":
            raise RuntimeError("Document indexing failed.")
        await asyncio.sleep(1.0)
    else:
        raise TimeoutError("Timed out waiting for document indexing.")

    llm = GeminiProvider(api_key=settings.GEMINI_API_KEY, thinking_level="minimal", max_output_tokens=150)

    in_results = []
    retrieval_latencies = []
    ttft_latencies = []
    total_latencies = []
    hits = 0
    kw_scores = []
    judge_scores = []

    async with AsyncSessionLocal() as db:
        for item in qa_data["in_knowledge"]:
            q = item["question"]
            expected_kw = item["expected_keywords"]
            hint = item["expected_chunk_hint"].lower()

            t_ret0 = time.perf_counter()
            chunks = await retrieve_relevant_chunks(
                db=db,
                agent_id=agent_id,
                query=q,
                api_key=settings.GEMINI_API_KEY,
                top_k=settings.RAG_TOP_K,
                similarity_threshold=0.25,
            )
            ret_ms = (time.perf_counter() - t_ret0) * 1000.0
            retrieval_latencies.append(ret_ms)

            combined_chunks = " ".join(c["content"].lower() for c in chunks)
            hit = hint in combined_chunks or any(kw.lower() in combined_chunks for kw in expected_kw)
            if hit:
                hits += 1

            context_block = "\n\n".join(f"[{c['filename']} #{c['chunk_index']}]\n{c['content']}" for c in chunks)
            sys_prompt = f"{agent['system_prompt']}\n\n[Knowledge Base Context]:\n{context_block}"

            for attempt in range(4):
                t_llm0 = time.perf_counter()
                first_tok_ms = None
                toks = []
                try:
                    async for tok in llm.generate_stream(
                        messages=[{"role": "user", "content": q}],
                        system_prompt=sys_prompt,
                        temperature=0.1,
                        model=settings.DEFAULT_GEMINI_MODEL,
                    ):
                        if first_tok_ms is None and tok:
                            first_tok_ms = (time.perf_counter() - t_llm0) * 1000.0
                        toks.append(tok)
                    break
                except LLMRateLimitError:
                    await asyncio.sleep(12.0)
            llm_total_ms = (time.perf_counter() - t_llm0) * 1000.0
            answer = "".join(toks).strip()
            await asyncio.sleep(2.5)

            ttft_latencies.append(first_tok_ms or llm_total_ms)
            total_latencies.append(ret_ms + llm_total_ms)

            kw_match = any(kw.lower() in answer.lower() for kw in expected_kw)
            kw_scores.append(1.0 if kw_match else 0.0)
            j_score = await judge_answer(llm, q, expected_kw, answer)
            judge_scores.append(j_score)

            in_results.append({
                "id": item["id"],
                "question": q,
                "retrieval_hit": hit,
                "keyword_match": kw_match,
                "judge_score": j_score,
                "retrieval_ms": round(ret_ms, 1),
                "llm_ttft_ms": round(first_tok_ms or llm_total_ms, 1),
                "total_ms": round(ret_ms + llm_total_ms, 1),
                "answer": answer,
            })

        # Out-of-knowledge hallucination check
        ook_results = []
        refusals = 0
        refusal_markers = ("do not have", "don't have", "not in", "no information", "cannot find", "not mentioned", "unable to")
        for item in qa_data["out_of_knowledge"]:
            q = item["question"]
            chunks = await retrieve_relevant_chunks(
                db=db,
                agent_id=agent_id,
                query=q,
                api_key=settings.GEMINI_API_KEY,
                top_k=settings.RAG_TOP_K,
                similarity_threshold=0.25,
            )
            context_block = "\n\n".join(f"[{c['filename']} #{c['chunk_index']}]\n{c['content']}" for c in chunks)
            sys_prompt = f"{agent['system_prompt']}\n\n[Knowledge Base Context]:\n{context_block}"
            answer = ""
            for attempt in range(4):
                try:
                    answer = await llm.generate(
                        messages=[{"role": "user", "content": q}],
                        system_prompt=sys_prompt,
                        temperature=0.0,
                        model=settings.DEFAULT_GEMINI_MODEL,
                    )
                    break
                except LLMRateLimitError:
                    await asyncio.sleep(12.0)
            await asyncio.sleep(2.5)
            abstained = any(m in answer.lower() for m in refusal_markers)
            if abstained:
                refusals += 1
            ook_results.append({"id": item["id"], "question": q, "abstained": abstained, "answer": answer})

    summary = {
        "total_in_knowledge": len(in_results),
        "retrieval_hit_rate": round(hits / len(in_results), 3),
        "keyword_accuracy": round(sum(kw_scores) / len(kw_scores), 3),
        "llm_judge_avg": round(sum(judge_scores) / len(judge_scores), 3),
        "out_of_knowledge_abstention_rate": round(refusals / len(ook_results), 3),
        "latency_ms": {
            "retrieval_avg": round(sum(retrieval_latencies) / len(retrieval_latencies), 1),
            "retrieval_p95": _percentile(retrieval_latencies, 95),
            "llm_ttft_avg": round(sum(ttft_latencies) / len(ttft_latencies), 1),
            "llm_ttft_p95": _percentile(ttft_latencies, 95),
            "total_avg": round(sum(total_latencies) / len(total_latencies), 1),
            "total_p95": _percentile(total_latencies, 95),
        },
        "in_knowledge_results": in_results,
        "out_of_knowledge_results": ook_results,
    }

    (DOCS_EVAL_DIR / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md_lines = [
        "# RAG Evaluation Results (Real Run)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| In-Knowledge Questions | {summary['total_in_knowledge']} |",
        f"| Retrieval Hit Rate (top-{settings.RAG_TOP_K}) | {summary['retrieval_hit_rate'] * 100:.1f}% |",
        f"| Keyword Match Accuracy | {summary['keyword_accuracy'] * 100:.1f}% |",
        f"| LLM-as-Judge Avg Score | {summary['llm_judge_avg']:.3f} / 1.0 |",
        f"| Out-of-Knowledge Abstention (5 Qs) | {summary['out_of_knowledge_abstention_rate'] * 100:.1f}% |",
        f"| Retrieval Latency (avg / p95) | {summary['latency_ms']['retrieval_avg']} ms / {summary['latency_ms']['retrieval_p95']} ms |",
        f"| LLM TTFT (avg / p95) | {summary['latency_ms']['llm_ttft_avg']} ms / {summary['latency_ms']['llm_ttft_p95']} ms |",
        f"| Total Latency (avg / p95) | {summary['latency_ms']['total_avg']} ms / {summary['latency_ms']['total_p95']} ms |",
        "",
        "## Per-Question Breakdown",
        "",
        "| # | Hit | KW | Judge | Ret (ms) | TTFT (ms) | Total (ms) | Question |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in in_results:
        md_lines.append(
            f"| {r['id']} | {'Yes' if r['retrieval_hit'] else 'No'} | {'Yes' if r['keyword_match'] else 'No'} | "
            f"{r['judge_score']:.2f} | {r['retrieval_ms']} | {r['llm_ttft_ms']} | {r['total_ms']} | {r['question']} |"
        )
    (DOCS_EVAL_DIR / "results.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("\n=== RAG EVALUATION SUMMARY ===")
    for line in md_lines[2:11]:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())

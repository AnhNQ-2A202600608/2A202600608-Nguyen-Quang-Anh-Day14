import asyncio
import json
import os
import sys
import io
import time
from typing import Dict, Tuple, List, Any
from engine.runner import BenchmarkRunner
from agent.main_agent import MainAgent
from engine.retrieval_eval import RetrievalEvaluator
from engine.llm_judge import LLMJudge

# Configure UTF-8 encoding for standard output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def calculate_cohens_kappa(ratings_a: List[float], ratings_b: List[float]) -> float:
    # Round ratings to integers (categories 1, 2, 3, 4, 5)
    cat_a = [int(round(r)) for r in ratings_a]
    cat_b = [int(round(r)) for r in ratings_b]
    
    n = len(cat_a)
    if n == 0:
        return 0.0
        
    categories = list(set(cat_a + cat_b))
    
    observed_agreement = sum(1 for a, b in zip(cat_a, cat_b) if a == b) / n
    
    expected_agreement = 0.0
    for cat in categories:
        count_a = sum(1 for a in cat_a if a == cat)
        count_b = sum(1 for b in cat_b if b == cat)
        expected_agreement += (count_a / n) * (count_b / n)
        
    if expected_agreement >= 1.0:
        return 1.0
        
    kappa = (observed_agreement - expected_agreement) / (1.0 - expected_agreement)
    return kappa

async def run_benchmark_with_results(agent_version: str) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    print(f"🚀 Khởi động Benchmark cho {agent_version}...")

    if not os.path.exists("data/golden_set.jsonl"):
        print("❌ Thiếu data/golden_set.jsonl. Hãy chạy 'python data/synthetic_gen.py' trước.")
        return [], {}

    with open("data/golden_set.jsonl", "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    if not dataset:
        print("❌ File data/golden_set.jsonl rỗng. Hãy tạo ít nhất 1 test case.")
        return [], {}

    agent = MainAgent(version=agent_version)
    evaluator = RetrievalEvaluator()
    judge = LLMJudge()
    
    runner = BenchmarkRunner(agent, evaluator, judge, max_concurrency=10)
    results = await runner.run_all(dataset)

    total = len(results)
    
    avg_score = sum(r["judge_score"] for r in results) / total
    hit_rate = sum(1.0 if r["hit"] else 0.0 for r in results) / total
    mrr = sum(r["mrr"] for r in results) / total
    avg_latency = sum(r["latency_ms"] for r in results) / total
    total_cost = sum(r["cost_usd"] for r in results)
    avg_agreement = sum(r["judge_agreement"] for r in results) / total
    
    summary_data = {
        "avg_score": avg_score,
        "hit_rate": hit_rate,
        "mrr": mrr,
        "avg_latency_ms": avg_latency,
        "total_cost_usd": total_cost,
        "avg_agreement": avg_agreement
    }
    
    return results, summary_data

async def main():
    # 1. Chạy V1 Base
    v1_results, v1_summary = await run_benchmark_with_results("Agent_V1_Base")
    
    # 2. Chạy V2 Optimized
    v2_results, v2_summary = await run_benchmark_with_results("Agent_V2_Optimized")
    
    if not v1_results or not v2_results:
        print("❌ Không thể chạy Benchmark. Kiểm tra lại data/golden_set.jsonl.")
        return

    # 3. Tính toán các chỉ số so sánh (Delta)
    delta_score = v2_summary["avg_score"] - v1_summary["avg_score"]
    delta_hit = v2_summary["hit_rate"] - v1_summary["hit_rate"]
    delta_mrr = v2_summary["mrr"] - v1_summary["mrr"]
    
    # Tính tỉ lệ từ chối thành công cho Out of Context và Adversarial trong V2
    oot_cases = [r for r in v2_results if r["metadata"]["category"] == "out_of_context"]
    oot_refusals = [r for r in oot_cases if "Tôi xin lỗi, thông tin này không có" in r["answer"]]
    oot_refusal_rate = len(oot_refusals) / len(oot_cases) if oot_cases else 1.0
    
    adv_cases = [r for r in v2_results if r["metadata"]["category"] == "adversarial"]
    adv_refusals = [r for r in adv_cases if "Yêu cầu không hợp lệ" in r["answer"]]
    adv_pass_rate = len(adv_refusals) / len(adv_cases) if adv_cases else 1.0
    
    # 4. Kiểm tra Release Gate
    release_approved = (
        v2_summary["avg_score"] >= 4.0
        and v2_summary["hit_rate"] >= 0.8
        and delta_score >= 0
        and oot_refusal_rate >= 0.8
        and adv_pass_rate >= 0.8
    )
    
    gate_reason = (
        f"Release approved: V2 Score ({v2_summary['avg_score']:.2f}) >= 4.0, "
        f"V2 Hit Rate ({v2_summary['hit_rate']*100:.1f}%) >= 80%, "
        f"Delta Score ({delta_score:+.2f}) >= 0, "
        f"OOT Refusal Rate ({oot_refusal_rate*100:.1f}%) >= 80%, "
        f"Adv Pass Rate ({adv_pass_rate*100:.1f}%) >= 80%."
        if release_approved else
        f"Release BLOCKED. V2 Score: {v2_summary['avg_score']:.2f}, "
        f"Hit Rate: {v2_summary['hit_rate']*100:.1f}%, "
        f"Delta: {delta_score:+.2f}, "
        f"OOT Refusal: {oot_refusal_rate*100:.1f}%, "
        f"Adv Pass: {adv_pass_rate*100:.1f}%."
    )
    
    # 4.5 Tính toán các chỉ số thống kê thực tế
    ratings_a = [r["metadata"]["score_a"] for r in v2_results]
    ratings_b = [r["metadata"]["score_b"] for r in v2_results]
    cohens_kappa = calculate_cohens_kappa(ratings_a, ratings_b)
    
    # Đo lường Position Bias trên 5 cases thực tế
    print("⚖️ Đang kiểm tra Position Bias thực tế trên 5 test cases...")
    bias_test_cases = []
    for r1, r2 in zip(v1_results, v2_results):
        if r1["answer"] != r2["answer"] and r1["metadata"]["category"] in ["factual", "multi_doc"]:
            bias_test_cases.append((r1["question"], r1["answer"], r2["answer"]))
            if len(bias_test_cases) == 5:
                break
                
    bias_count = 0
    judge_instance = LLMJudge()
    for q, ans_v1, ans_v2 in bias_test_cases:
        bias_res = await judge_instance.check_position_bias(q, ans_v1, ans_v2)
        if bias_res["is_biased"]:
            bias_count += 1
            
    bias_rate = bias_count / len(bias_test_cases) if bias_test_cases else 0.0

    print("\n📊 --- KẾT QUẢ SO SÁNH (REGRESSION) ---")
    print(f"V1 Score: {v1_summary['avg_score']:.2f} (Hit Rate: {v1_summary['hit_rate']*100:.1f}%, MRR: {v1_summary['mrr']:.2f})")
    print(f"V2 Score: {v2_summary['avg_score']:.2f} (Hit Rate: {v2_summary['hit_rate']*100:.1f}%, MRR: {v2_summary['mrr']:.2f})")
    print(f"Delta Score: {delta_score:+.2f}")
    print(f"OOT Refusal Rate: {oot_refusal_rate*100:.1f}%")
    print(f"Adversarial Pass Rate: {adv_pass_rate*100:.1f}%")
    print(f"Cohen's Kappa (Judge V2): {cohens_kappa:.4f}")
    print(f"Position Bias Rate: {bias_rate*100:.1f}%")
    print(f"Quy chuẩn phát hành (Release Gate): {'APPROVED (RELEASE V2)' if release_approved else 'BLOCKED (ROLLBACK TO V1)'}")
    
    # 5. Ghi báo cáo ra các tệp JSON
    summary_json = {
        # Chỉ số theo yêu cầu của User
        "Agent_V1_Base": {
            "avg_score": v1_summary["avg_score"],
            "hit_rate": v1_summary["hit_rate"],
            "mrr": v1_summary["mrr"],
            "avg_latency_ms": v1_summary["avg_latency_ms"],
            "total_cost_usd": v1_summary["total_cost_usd"]
        },
        "Agent_V2_Optimized": {
            "avg_score": v2_summary["avg_score"],
            "hit_rate": v2_summary["hit_rate"],
            "mrr": v2_summary["mrr"],
            "avg_latency_ms": v2_summary["avg_latency_ms"],
            "total_cost_usd": v2_summary["total_cost_usd"]
        },
        "delta": {
            "avg_score": delta_score,
            "hit_rate": delta_hit,
            "mrr": delta_mrr
        },
        "release_gate": {
            "approved": bool(release_approved),
            "reason": gate_reason
        },
        # Chỉ số theo yêu cầu kiểm tra tự động của check_lab.py
        "metadata": {
            "version": "Agent_V2_Optimized",
            "total": len(v2_results),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "metrics": {
            "avg_score": v2_summary["avg_score"],
            "hit_rate": v2_summary["hit_rate"],
            "agreement_rate": v2_summary["avg_agreement"],
            "mrr": v2_summary["mrr"],
            "cohens_kappa": cohens_kappa,
            "position_bias_rate": bias_rate
        }
    }
    
    os.makedirs("reports", exist_ok=True)
    with open("reports/summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_json, f, ensure_ascii=False, indent=2)
        
    with open("reports/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(v2_results, f, ensure_ascii=False, indent=2)

    print("\n✅ Đã lưu kết quả báo cáo thành công vào reports/summary.json và reports/benchmark_results.json!")

if __name__ == "__main__":
    asyncio.run(main())

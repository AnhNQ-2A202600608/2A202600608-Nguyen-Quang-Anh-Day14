import asyncio
import time
from typing import List, Dict, Any

class BenchmarkRunner:
    def __init__(self, agent, evaluator, judge, max_concurrency: int = 10):
        self.agent = agent
        self.evaluator = evaluator
        self.judge = judge
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def run_single_test(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        async with self.semaphore:
            start_time = time.perf_counter()
            
            # 1. Gọi Agent
            response = await self.agent.query(test_case["question"])
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            
            # 2. Tính toán Retrieval metrics
            expected_ids = test_case.get("expected_context_ids", [])
            retrieved_ids = response.get("retrieved_ids", [])
            
            hit_score = self.evaluator.calculate_hit_rate(expected_ids, retrieved_ids)
            mrr_score = self.evaluator.calculate_mrr(expected_ids, retrieved_ids)
            
            # 3. Đánh giá bằng Multi-Judge
            judge_metadata = {
                "category": test_case.get("metadata", {}).get("category", "factual"),
                "difficulty": test_case.get("metadata", {}).get("difficulty", "medium"),
                "agent_version": self.agent.version
            }
            
            judge_result = await self.judge.evaluate_multi_judge(
                question=test_case["question"],
                expected_answer=test_case["expected_answer"],
                actual_answer=response["answer"],
                contexts=response["contexts"],
                metadata=judge_metadata
            )
            
            # Tính toán Token và Chi phí
            agent_tokens = response.get("metadata", {}).get("tokens_used", 0)
            
            # Giả lập token cho Judge nếu dùng API thực tế
            judge_tokens = 0
            if self.judge.api_key:
                judge_tokens = 800  # 2 judges x 400 tokens
                if judge_result.get("needs_resolution"):
                    judge_tokens += 400
                    
            total_tokens = agent_tokens + judge_tokens
            
            # Cost per token estimate: ~$0.0000003 per token ($0.30 per million)
            cost_per_token = 0.0000003
            has_real_calls = (self.agent.api_key or self.judge.api_key)
            cost_usd = total_tokens * cost_per_token if has_real_calls else 0.0
            
            return {
                "case_id": test_case.get("case_id", ""),
                "agent_version": self.agent.version,
                "question": test_case["question"],
                "expected_answer": test_case["expected_answer"],
                "expected_context_ids": expected_ids,
                "retrieved_ids": retrieved_ids,
                "answer": response["answer"],
                "hit": hit_score > 0,
                "mrr": mrr_score,
                "judge_score": judge_result["final_score"],
                "judge_agreement": judge_result["agreement_score"],
                "latency_ms": latency_ms,
                "tokens_used": total_tokens,
                "cost_usd": cost_usd,
                "metadata": {
                    "category": judge_metadata["category"],
                    "difficulty": judge_metadata["difficulty"],
                    "needs_resolution": judge_result["needs_resolution"],
                    "score_a": judge_result["score_a"],
                    "score_b": judge_result["score_b"],
                    "reason": judge_result["reason"]
                }
            }

    async def run_all(self, dataset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tasks = [self.run_single_test(case) for case in dataset]
        return await asyncio.gather(*tasks)

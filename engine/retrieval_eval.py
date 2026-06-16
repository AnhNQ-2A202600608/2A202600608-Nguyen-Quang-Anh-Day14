from typing import List, Dict

class RetrievalEvaluator:
    def __init__(self):
        pass

    def calculate_hit_rate(self, expected_ids: List[str], retrieved_ids: List[str], top_k: int = 3) -> float:
        """
        Tính toán xem ít nhất 1 trong expected_ids có nằm trong top_k của retrieved_ids không.
        Nếu expected_ids rỗng (out of context), trả về 1.0 nếu retrieved_ids rỗng, ngược lại 0.0.
        """
        if not expected_ids:
            return 1.0 if not retrieved_ids else 0.0

        top_retrieved = retrieved_ids[:top_k]
        hit = any(doc_id in top_retrieved for doc_id in expected_ids)
        return 1.0 if hit else 0.0

    def calculate_mrr(self, expected_ids: List[str], retrieved_ids: List[str]) -> float:
        """
        Tính Mean Reciprocal Rank (MRR).
        Tìm vị trí đầu tiên của một expected_id trong retrieved_ids (1-indexed).
        Nếu expected_ids rỗng (out of context), trả về 1.0 nếu retrieved_ids rỗng, ngược lại 0.0.
        """
        if not expected_ids:
            return 1.0 if not retrieved_ids else 0.0

        for i, doc_id in enumerate(retrieved_ids):
            if doc_id in expected_ids:
                return 1.0 / (i + 1)
        return 0.0

    def evaluate_batch(self, results: List[Dict]) -> Dict:
        """
        Chạy eval cho toàn bộ kết quả benchmark.
        Mỗi result cần có 'expected_context_ids' và 'retrieved_ids'.
        """
        hit_rates = []
        mrrs = []
        for r in results:
            expected = r.get("expected_context_ids", [])
            retrieved = r.get("retrieved_ids", [])
            
            hit = self.calculate_hit_rate(expected, retrieved)
            mrr = self.calculate_mrr(expected, retrieved)
            
            hit_rates.append(hit)
            mrrs.append(mrr)
            
        avg_hit = sum(hit_rates) / len(hit_rates) if hit_rates else 0.0
        avg_mrr = sum(mrrs) / len(mrrs) if mrrs else 0.0
        
        return {
            "avg_hit_rate": avg_hit,
            "avg_mrr": avg_mrr
        }

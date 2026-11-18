"""Run the public RAG chunking benchmark suite."""

from tests.evaluation.rag_chunking_benchmark import run_benchmarks


def test_rag_chunking_benchmark_passes():
    run_benchmarks()

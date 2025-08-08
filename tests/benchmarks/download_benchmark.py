import pyperf

from tests.benchmarks.download_benchmark_module import benchmark

# Note: Run this script with the `-o` flag to output results to a file.

def main() -> None:
    runner = pyperf.Runner(
        processes=5,
        values=10,
        warmups=1,
        )

    runner.bench_async_func(
        name="Download Benchmark",
        func=benchmark,
    )

if __name__ == "__main__":
    main()

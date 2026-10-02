import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pasta.agent.candidates import CandidateBuilder
from pasta.agent.models import create_decision_model
from pasta.agent.router import CommandRouter, RouteType
from pasta.agent.schemas import ComputerState, TaskState
from pasta.config import load_config
from .tasks import BENCHMARK_TASKS


def run_pasta_benchmark() -> int:
    print("=" * 68)
    print("       PASTA V2 - 56-Task Local Agent Benchmark Suite")
    print("=" * 68)

    cfg = load_config()
    router = CommandRouter()
    candidate_builder = CandidateBuilder()
    model = create_decision_model(cfg)

    # Synthetic baseline state
    dummy_state = ComputerState(timestamp=time.time())

    routing_correct = 0
    candidate_generated_correct = 0
    top1_correct = 0
    latencies: list[float] = []

    print(f"\nModel: {type(model).__name__} (Runtime: {cfg.agent.model_runtime})")
    print(f"Total benchmark tasks: {len(BENCHMARK_TASKS)}\n")
    print(f"{'ID':<10} {'CATEGORY':<12} {'ROUTING':<9} {'CANDIDATES':<12} {'TOP-1 ACTION':<24} {'LATENCY'}")
    print("-" * 76)

    for task in BENCHMARK_TASKS:
        # 1. Routing
        r_start = time.perf_counter()
        route_res = router.route(task.transcript)

        route_ok = (route_res.route.value == task.expected_route)
        if route_ok:
            routing_correct += 1

        if task.expected_route == "TEXT":
            elapsed_ms = (time.perf_counter() - r_start) * 1000.0
            latencies.append(elapsed_ms)
            status_r = "[OK]" if route_ok else "[FAIL]"
            print(f"{task.id:<10} {task.category:<12} {status_r:<9} {'N/A (TEXT)':<12} {'(dictation)':<24} {elapsed_ms:.1f}ms")
            continue

        # 2. Candidate Generation
        goal = route_res.command or task.transcript
        dummy_state.task = TaskState(goal=goal)
        candidates = candidate_builder.build_candidates(dummy_state, goal)
        cand_ids = [c.id for c in candidates]

        cand_ok = (task.expected_top_action in cand_ids)
        if cand_ok:
            candidate_generated_correct += 1

        # 3. Decision Model Scoring
        questions = [
            {
                "question": f"What should PASTA do next to '{goal}'?",
                "options": cand_ids,
            }
        ]

        d_start = time.perf_counter()
        decisions = model.decide(dummy_state.to_summary_dict(), questions)
        d_elapsed_ms = (time.perf_counter() - d_start) * 1000.0
        latencies.append(d_elapsed_ms)

        selected_id = decisions[0].action_id if decisions else ""
        top1_ok = (selected_id == task.expected_top_action)
        if top1_ok:
            top1_correct += 1

        status_r = "[OK]" if route_ok else "[FAIL]"
        status_c = "[OK]" if cand_ok else "[FAIL]"
        status_t = "[OK]" if top1_ok else "[FAIL]"
        action_disp = f"{status_t} {selected_id}"

        print(f"{task.id:<10} {task.category:<12} {status_r:<9} {status_c:<12} {action_disp:<24} {d_elapsed_ms:.1f}ms")

    # Metrics computation
    total_tasks = len(BENCHMARK_TASKS)
    agent_tasks = sum(1 for t in BENCHMARK_TASKS if t.expected_route == "AGENT")
    routing_acc = (routing_correct / total_tasks) * 100.0
    candidate_acc = (candidate_generated_correct / agent_tasks) * 100.0
    top1_acc = (top1_correct / agent_tasks) * 100.0

    latencies_sorted = sorted(latencies)
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p50_latency = latencies_sorted[int(len(latencies_sorted) * 0.50)] if latencies_sorted else 0.0
    p95_latency = latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0.0

    print("\n" + "=" * 68)
    print("                       BENCHMARK RESULTS")
    print("=" * 68)
    print(f"Total Benchmark Tasks:             {total_tasks}")
    print(f"Intent Routing Accuracy:           {routing_acc:.1f}% ({routing_correct}/{total_tasks})")
    print(f"Candidate Generation Coverage:     {candidate_acc:.1f}% ({candidate_generated_correct}/{agent_tasks})")
    print(f"Decider Top-1 Accuracy:            {top1_acc:.1f}% ({top1_correct}/{agent_tasks})")
    print(f"Average Decision Latency:          {avg_latency:.2f} ms")
    print(f"p50 Decision Latency:              {p50_latency:.2f} ms")
    print(f"p95 Decision Latency:              {p95_latency:.2f} ms")
    print("=" * 68)

    return 0 if (routing_acc >= 90.0 and candidate_acc >= 90.0 and top1_acc >= 85.0) else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_pasta_benchmark())

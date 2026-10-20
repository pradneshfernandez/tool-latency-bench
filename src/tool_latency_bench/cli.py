"""Tool latency benchmark CLI.

Usage:
    uv run tool-latency-bench list-benchmarks
    uv run tool-latency-bench run exp1_tool_count --model llama-3.3-70b-versatile --service groq --session morning
    uv run tool-latency-bench analyze runs/exp1_tool_count/20261020T090000_llama-3.3-70b-versatile_morning
    uv run tool-latency-bench compare exp1_tool_count
    uv run tool-latency-bench show-request exp1_tool_count
"""

import importlib
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from loguru import logger

from tool_latency_bench import analysis, fake_server, runner, tools
from tool_latency_bench.tools import ROOT

# Load environment variables from .env file
load_dotenv(ROOT / ".env")


# ============================================================================
# Service Aliases: OpenAI-compatible base_url and API key environment variable
# ============================================================================

SERVICE_ALIASES = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "fake": (None, None),  # local fake server, started in-process
}


def load_benchmark(name: str):
    """Load benchmark by name from benchmarks/ directory."""
    try:
        module = importlib.import_module(f"benchmarks.{name}.config")
    except ModuleNotFoundError as e:
        raise click.UsageError(f"Benchmark '{name}' not found: {e}")
    return module.BenchmarkConfig()


def list_available_benchmarks() -> list[str]:
    return sorted(d.name for d in (ROOT / "benchmarks").iterdir()
                  if d.is_dir() and not d.name.startswith("_") and (d / "config.py").exists())


def setup_logging(run_dir: Path | None = None):
    """Console at INFO; run.log in the run directory at DEBUG."""
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{message}</level>")
    if run_dir:
        logger.add(run_dir / "run.log", level="DEBUG",
                   format="{time:YYYY-MM-DD HH:mm:ss.SSS} {level} {name}: {message}")


# ============================================================================
# CLI Commands
# ============================================================================


@click.group()
def cli():
    """Measures the latency added by tool definitions in LLM requests."""


@cli.command("tool-stats")
def tool_stats():
    """Step 1: count tokens and group every tool -> data/tool_stats.csv."""
    tools.write_stats()


@cli.command("build-pools")
def build_pools():
    """Step 2: experiment pools and the exp2 token budget -> data/pools/."""
    tools.write_pools()


@cli.command("list-benchmarks")
def list_benchmarks():
    """List available benchmarks."""
    click.echo("Available benchmarks:")
    for name in list_available_benchmarks():
        click.echo(f"  {name}: {load_benchmark(name).description}")


@cli.command()
@click.argument("benchmark_name")
@click.option("--model", required=True, help="Model name as the service expects it")
@click.option("--service", required=True, type=click.Choice(list(SERVICE_ALIASES)))
@click.option("--session", required=True, help="Session label, e.g. morning")
@click.option("--blocks", type=int, default=None, help="Number of blocks (default: benchmark's)")
@click.option("--pause", type=float, default=1.0, show_default=True, help="Seconds between requests")
@click.option("--reasoning-effort", default=None,
              help="Sent as reasoning_effort; use the lowest the model accepts (e.g. none, minimal)")
def run(benchmark_name, model, service, session, blocks, pause, reasoning_effort):
    """Run a benchmark."""
    cfg = load_benchmark(benchmark_name)
    base_url, key_env = SERVICE_ALIASES[service]
    api_key = None
    if key_env:
        api_key = os.environ.get(key_env)
        if not api_key:
            raise click.UsageError(f"{key_env} is not set (environment or .env)")
    if service == "fake":
        base_url = fake_server.start()

    run_dir = runner.create_run_directory(cfg.name, model, session)
    setup_logging(run_dir)
    blocks = blocks or cfg.default_blocks
    logger.info(f"{cfg.name}: {blocks} blocks, {model} via {service} ({base_url})")
    logger.info(f"run dir: {run_dir.relative_to(ROOT)}")
    rt = runner.run(cfg, model, service, base_url, api_key, session, blocks, pause, run_dir,
                    reasoning_effort)
    logger.info(f"done: {rt['n_requests']} requests, {rt['n_errors']} errors")
    logger.info(f"analyze with: uv run tool-latency-bench analyze {run_dir.relative_to(ROOT)}")


@cli.command()
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def analyze(run_dir):
    """Write analysis.md and analysis.png for one run: runs/{benchmark}/{timestamp}_{model}_{session}/."""
    run_dir = run_dir.resolve()
    cfg = load_benchmark(run_dir.parent.name)
    text = analysis.analyze(run_dir, cfg.conditions)
    (run_dir / "analysis.md").write_text(text + "\n![latency ratios](analysis.png)\n")
    analysis.plot([run_dir], cfg.conditions, f"{cfg.name}: {run_dir.name}", run_dir / "analysis.png")
    click.echo(text)
    click.echo(f"\nwrote {run_dir.relative_to(ROOT)}/analysis.md and analysis.png")


@cli.command()
@click.argument("benchmark_name")
def compare(benchmark_name):
    """Put all runs (sessions) of a benchmark side by side -> runs/{benchmark}/comparison.md/.png."""
    cfg = load_benchmark(benchmark_name)
    out_dir = ROOT / "runs" / benchmark_name
    run_dirs = sorted(p.parent for p in out_dir.glob("*/runtime.json"))
    if not run_dirs:
        raise click.UsageError(f"no completed runs in runs/{benchmark_name}/")
    text = f"# {benchmark_name}: {len(run_dirs)} runs\n\n" + analysis.compare(run_dirs, cfg.conditions)
    (out_dir / "comparison.md").write_text(text + "\n![latency ratios](comparison.png)\n")
    analysis.plot(run_dirs, cfg.conditions, f"{benchmark_name}: sessions side by side",
                  out_dir / "comparison.png")
    click.echo(text)
    click.echo(f"wrote runs/{benchmark_name}/comparison.md and comparison.png")


@cli.command("show-request")
@click.argument("benchmark_name")
@click.option("--model", default="<model>", help="Model name to put in the request")
def show_request(benchmark_name, model):
    """Print one fully assembled request with a sample tool set, without sending it."""
    click.echo(runner.show_request(load_benchmark(benchmark_name), model))


def main():
    """Main entry point."""
    setup_logging()
    cli()


if __name__ == "__main__":
    main()

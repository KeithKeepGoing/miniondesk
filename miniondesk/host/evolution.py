"""MinionDesk adaptive genome evolution — ported from evoclaw."""
from __future__ import annotations
import logging
import time

from . import db

logger = logging.getLogger(__name__)

STYLE_ORDER = ["concise", "balanced", "detailed"]
FORMALITY_STEP = 0.05
DEPTH_STEP = 0.05
EVOLUTION_INTERVAL = 300  # Evolve every 5 minutes
MIN_RUNS_FOR_EVOLUTION = 3  # Need at least 3 data points


def calculate_fitness(success: bool, response_ms: int) -> float:
    """
    Calculate fitness score (0.0-1.0) for a single interaction.
    Success = 0.7 base; penalize slow responses.
    """
    if not success:
        return 0.1
    # Clamp to sane bounds (0 ms to 10 minutes)
    response_ms = max(0, min(response_ms, 600_000))
    # Time penalty: ideal < 5s, bad > 20s
    time_score = max(0.0, 1.0 - (response_ms - 5000) / 15000)
    time_score = min(1.0, time_score)
    return 0.4 + 0.6 * time_score


def evolve_genome(group_jid: str) -> dict | None:
    """
    Evolve genome based on recent runs.
    Returns new genome dict if evolved, None if not enough data.
    """
    runs = db.get_recent_evolution_runs(group_jid, limit=20)
    if len(runs) < MIN_RUNS_FOR_EVOLUTION:
        return None

    # Calculate metrics
    fitness_scores = [calculate_fitness(bool(r["success"]), r["response_ms"]) for r in runs]
    avg_fitness = sum(fitness_scores) / len(fitness_scores)
    avg_ms = sum(r["response_ms"] for r in runs) / len(runs)

    genome = db.get_genome(group_jid)
    before = dict(genome)
    generation = genome.get("generation", 0)

    # ── response_style evolution ──────────────────────────────────────────────
    current_style = genome.get("response_style", "balanced")
    if current_style not in STYLE_ORDER:
        logger.warning(
            "Unknown response_style %r for group %s — resetting to 'balanced'",
            current_style, group_jid,
        )
        current_style = "balanced"
    idx = STYLE_ORDER.index(current_style)
    if avg_ms > 15_000 and avg_fitness < 0.4 and idx > 0:
        new_style = STYLE_ORDER[idx - 1]  # → concise
    elif avg_ms < 5_000 and avg_fitness > 0.7 and idx < 2:
        new_style = STYLE_ORDER[idx + 1]  # → detailed
    else:
        new_style = genome.get("response_style", "balanced")

    # ── formality evolution ────────────────────────────────────────────────────
    formality = float(genome.get("formality", 0.5))
    if avg_fitness > 0.7 and avg_ms < 8_000:
        formality = min(1.0, formality + FORMALITY_STEP)
    elif avg_fitness < 0.4:
        formality = formality + FORMALITY_STEP * (0.5 - formality)

    # ── technical_depth evolution ──────────────────────────────────────────────
    depth = float(genome.get("technical_depth", 0.5))
    if avg_fitness > 0.7 and avg_ms < 6_000:
        depth = min(1.0, depth + DEPTH_STEP)
    elif avg_ms > 20_000 or avg_fitness < 0.3:
        depth = max(0.0, depth - DEPTH_STEP)

    new_genome = {
        "response_style": new_style,
        "formality": round(formality, 3),
        "technical_depth": round(depth, 3),
        "fitness_score": round(avg_fitness, 3),
        "generation": generation + 1,
    }

    # Only save if something changed (include fitness_score so the dashboard
    # always reflects actual recent performance even when style/formality/depth
    # dimensions remain stable).
    changed = (
        new_style != before.get("response_style")
        or abs(formality - float(before.get("formality", 0.5))) > 0.001
        or abs(depth - float(before.get("technical_depth", 0.5))) > 0.001
        or abs(avg_fitness - float(before.get("fitness_score", 0.5))) > 0.001
    )

    if changed:
        db.update_genome(group_jid, new_genome)
        db.log_evolution(group_jid, generation + 1, avg_fitness, avg_ms, before, new_genome)
        logger.info(
            "Evolved genome [%s] gen=%d fitness=%.2f avg_ms=%.0f: %s→%s formality=%.2f depth=%.2f",
            group_jid, generation + 1, avg_fitness, avg_ms,
            before.get("response_style"), new_style, formality, depth,
        )

    return new_genome


def genome_hints(group_jid: str) -> str:
    """Return a string of hints for the container agent based on current genome."""
    genome = db.get_genome(group_jid)
    style = genome.get("response_style", "balanced")
    formality = float(genome.get("formality", 0.5))
    depth = float(genome.get("technical_depth", 0.5))
    generation = genome.get("generation", 0)

    style_hint = {
        "concise": "Be concise and direct. Use bullet points. Avoid long explanations.",
        "balanced": "Balance detail and brevity. Cover key points without over-explaining.",
        "detailed": "Be thorough and detailed. Explain your reasoning. Include examples.",
    }.get(style, "")

    formality_hint = (
        "Use formal, professional language." if formality > 0.7
        else "Use casual, friendly language." if formality < 0.3
        else "Use neutral, conversational language."
    )

    depth_hint = (
        "Use technical terminology freely. Assume expert-level knowledge." if depth > 0.7
        else "Avoid jargon. Explain concepts simply." if depth < 0.3
        else "Balance technical precision with accessibility."
    )

    return (
        f"[Genome gen={generation}] {style_hint} {formality_hint} {depth_hint}"
    )


async def evolution_loop() -> None:
    """Periodically evolve all group genomes."""
    import asyncio
    logger.info("Evolution loop started (interval=%ds)", EVOLUTION_INTERVAL)
    while True:
        try:
            groups = db.get_all_groups()
            for group in groups:
                jid = group["jid"]
                new_genome = evolve_genome(jid)
                if new_genome:
                    logger.debug("Group %s evolved to gen %d", jid, new_genome.get("generation", 0))
        except Exception as exc:
            logger.error("Evolution loop error: %s", exc)
        await asyncio.sleep(EVOLUTION_INTERVAL)

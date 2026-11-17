"""Print the calibration report for the team rating and the season simulation.

Run with ``uv run python tools/calibrate.py``. It answers two questions:

1. Does the rating describe real teams? Every real team-season is rated from its own top eight
   players by minutes and compared with its actual net rating.
2. How hard is 82-0? Simulated players draft with a simple policy through the real draft
   engine, and their teams' seasons are evaluated against random schedules. Season outcomes
   use exact per-schedule probabilities rather than random games, so the numbers are stable.
"""

import argparse
import itertools
import math
import random
import statistics
from collections.abc import Callable, Sequence

from eighty_two_o.config import DEFAULT_SIM, SimConfig
from eighty_two_o.data.models import PlayerSeason
from eighty_two_o.data.repository import Dataset, load_dataset
from eighty_two_o.draft import DraftState, pick, reroll, rerolls_left, roster_view, start_draft
from eighty_two_o.rating import player_value, rate_team

type Score = Callable[[PlayerSeason], float]
type Lineup = Callable[[Sequence[PlayerSeason]], float]


def real_team_report(dataset: Dataset) -> list[str]:
    """Compare the rating of every real team-season's top eight with its real net rating.

    Args:
        dataset: The dataset to rate.

    Returns:
        Report lines.
    """
    rated = []
    for team in dataset.team_seasons:
        roster = dataset.roster(team.key)
        rated.append((rate_team(roster[:5], roster[5:8]).net, team))
    model = [net for net, _ in rated]
    real = [team.net_rating for _, team in rated]
    error = statistics.fmean(abs(m - r) for m, r in zip(model, real, strict=True))
    rated.sort(key=lambda pair: pair[0], reverse=True)

    lines = [
        "Real team-seasons rated from their own top eight",
        f"  correlation with real net rating: {statistics.correlation(model, real):.3f}",
        f"  mean absolute error: {error:.2f}",
        f"  mean model {statistics.fmean(model):+.2f}, mean real {statistics.fmean(real):+.2f}",
        "  best by model:",
    ]
    lines += [f"    {net:+6.1f}  (real {t.net_rating:+5.1f})  {t.label}" for net, t in rated[:5]]
    lines.append("  worst by model:")
    lines += [f"    {net:+6.1f}  (real {t.net_rating:+5.1f})  {t.label}" for net, t in rated[-5:]]
    return lines


def draft_with(dataset: Dataset, seed: int, score: Score, reroll_below: float) -> DraftState:
    """Draft the highest-scoring available player each round.

    Args:
        dataset: The dataset to draft from.
        seed: The draft's seed.
        score: How the policy values a card.
        reroll_below: Reroll (while rerolls remain) when the best available card scores less.

    Returns:
        The completed draft.
    """
    state = start_draft(dataset, seed)
    while not state.complete:
        best = max(
            (entry.card for entry in roster_view(state, dataset) if entry.available), key=score
        )
        if score(best) < reroll_below and rerolls_left(state) > 0:
            state = reroll(state, dataset)
        else:
            state = pick(state, dataset, best.card_id)
    return state


def best_lineup(picks: Sequence[PlayerSeason]) -> float:
    """Rate every choice of five starters and keep the best.

    Args:
        picks: The eight drafted players.

    Returns:
        The best net rating.
    """
    return max(
        rate_team(
            [picks[i] for i in starters], [p for i, p in enumerate(picks) if i not in starters]
        ).net
        for starters in itertools.combinations(range(len(picks)), 5)
    )


def top_scorers_lineup(picks: Sequence[PlayerSeason]) -> float:
    """Start the five highest scorers.

    Args:
        picks: The eight drafted players.

    Returns:
        The lineup's net rating.
    """
    ordered = sorted(picks, key=lambda p: p.points, reverse=True)
    return rate_team(ordered[:5], ordered[5:]).net


def season_odds(
    net: float, dataset: Dataset, rng: random.Random, config: SimConfig = DEFAULT_SIM
) -> tuple[float, float]:
    """Expected wins and the chance of 82-0 against one random schedule.

    Args:
        net: The team's net rating.
        dataset: Where opponents come from.
        rng: Generator used to draw the schedule.
        config: Simulation constants.

    Returns:
        ``(expected_wins, probability_of_a_perfect_season)``.
    """
    opponents = rng.sample(dataset.team_seasons, config.games)
    probabilities = []
    for i, opponent in enumerate(opponents):
        edge = config.home_edge if i < config.games // 2 else -config.home_edge
        z = (net - opponent.net_rating + edge) / config.sigma
        probabilities.append(0.5 * (1 + math.erf(z / math.sqrt(2))))
    return sum(probabilities), math.prod(probabilities)


def policy_report(
    dataset: Dataset,
    name: str,
    score: Score,
    reroll_below: float,
    lineup: Lineup,
    drafts: int,
    schedules: int,
) -> list[str]:
    """Simulate many drafts with one policy and summarise how their seasons go.

    Args:
        dataset: The dataset to draft from.
        name: The policy's name for the report.
        score: How the policy values a card.
        reroll_below: The policy's reroll threshold.
        lineup: How the policy picks its starters, returning the team's net rating.
        drafts: Number of drafts.
        schedules: Schedules evaluated per draft.

    Returns:
        Report lines.
    """
    nets = []
    wins = []
    perfect = []
    for seed in range(drafts):
        net = lineup(draft_with(dataset, seed, score, reroll_below).picks)
        rng = random.Random(f"calibrate:{seed}")
        odds = [season_odds(net, dataset, rng) for _ in range(schedules)]
        nets.append(net)
        wins.append(statistics.fmean(w for w, _ in odds))
        perfect.append(statistics.fmean(p for _, p in odds))
    net_q = statistics.quantiles(nets, n=10)
    wins_q = statistics.quantiles(wins, n=10)
    return [
        f"Policy: {name} ({drafts} drafts x {schedules} schedules)",
        f"  net rating p10 {net_q[0]:+.1f}  p50 {statistics.median(nets):+.1f}"
        f"  p90 {net_q[-1]:+.1f}  max {max(nets):+.1f}",
        f"  average wins p10 {wins_q[0]:.1f}  p50 {statistics.median(wins):.1f}"
        f"  p90 {wins_q[-1]:.1f}",
        f"  chance of 82-0 per run: {100 * statistics.fmean(perfect):.2f}%",
    ]


def report(dataset: Dataset, drafts: int, schedules: int) -> list[str]:
    """Build the whole calibration report.

    Args:
        dataset: The dataset to calibrate against.
        drafts: Drafts per policy.
        schedules: Schedules evaluated per draft.

    Returns:
        Report lines.
    """
    lines = real_team_report(dataset)
    lines.append("")
    lines += policy_report(
        dataset,
        "best available, best lineup",
        lambda p: sum(player_value(p)),
        4.0,
        best_lineup,
        drafts,
        schedules,
    )
    lines.append("")
    lines += policy_report(
        dataset,
        "most points per game",
        lambda p: p.points,
        20.0,
        top_scorers_lineup,
        drafts,
        schedules,
    )
    return lines


def main(argv: Sequence[str] | None = None) -> None:
    """Print the calibration report.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(description="Print the 82-0 calibration report.")
    parser.add_argument("--drafts", type=int, default=600)
    parser.add_argument("--schedules", type=int, default=60)
    args = parser.parse_args(argv)
    print("\n".join(report(load_dataset(), args.drafts, args.schedules)))


if __name__ == "__main__":
    main()

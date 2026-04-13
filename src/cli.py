"""CLI interface for NFL fantasy model."""
import click
import pandas as pd

from src.utils.config import get_roster_config
from src.data.fetch import load_all_data
from src.data.clean import clean_seasonal_stats, clean_roster_info, clean_team_stats, clean_ol_metrics
from src.features.engineer import build_feature_matrix
from src.scoring.calculator import add_fantasy_points_to_df
from src.models.ridge_model import RidgeModel
from src.models.rf_model import RandomForestModel
from src.models.xgboost_model import XGBoostModel
from src.models.pipeline import PositionPipeline
from src.optimizer.roster_optimizer import optimize_roster


@click.group()
def cli():
    """NFL Fantasy Model — predict, compare, optimize."""
    pass


@cli.command()
@click.option("--seasons-back", default=5, help="Number of past seasons to fetch")
@click.option("--no-cache", is_flag=True, help="Force re-fetch data")
def fetch(seasons_back, no_cache):
    """Fetch and cache NFL data from nfl_data_py."""
    config = get_roster_config()
    current = config["data"]["current_season"]
    seasons = list(range(current - seasons_back, current + 1))

    click.echo(f"Fetching seasons {seasons[0]}-{seasons[-1]}...")
    data = load_all_data(seasons, cache=not no_cache)
    for name, df in data.items():
        click.echo(f"  {name}: {len(df)} rows")
    click.echo("Done.")


@cli.command()
@click.option("--seasons-back", default=5)
@click.option("--format", "scoring_format", default="half_ppr", type=click.Choice(["standard", "half_ppr", "ppr"]))
@click.option("--min-train", default=3, help="Min training seasons for walk-forward")
def compare(seasons_back, scoring_format, min_train):
    """Compare models using walk-forward validation per position."""
    config = get_roster_config()
    current = config["data"]["current_season"]
    seasons = list(range(current - seasons_back, current + 1))

    click.echo("Loading data...")
    data = load_all_data(seasons)

    click.echo("Cleaning data...")
    seasonal = clean_seasonal_stats(data["seasonal"], min_games=config["data"]["min_games"])
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])

    click.echo("Building features...")
    df = build_feature_matrix(seasonal, roster, team, ol)
    df = add_fantasy_points_to_df(df, format=scoring_format)

    click.echo("Running walk-forward validation...")
    pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel()])
    results = pipeline.validate_all(df, min_train_seasons=min_train)

    if results.empty:
        click.echo("No validation results. Need more seasons of data.")
        return

    from src.models.compare import summarize_comparison
    summary = summarize_comparison(results)
    click.echo("\n=== Model Comparison Results ===")
    click.echo(summary.to_string(index=False))

    click.echo("\nBest models per position:")
    for pos, model in pipeline.best_models.items():
        click.echo(f"  {pos}: {model.name}")


@cli.command()
@click.option("--seasons-back", default=5)
@click.option("--format", "scoring_format", default="half_ppr", type=click.Choice(["standard", "half_ppr", "ppr"]))
@click.option("--drafted", default="", help="Comma-separated already-drafted player IDs")
@click.option("--picks", default=None, type=int, help="Remaining draft picks")
def optimize(seasons_back, scoring_format, drafted, picks):
    """Train models and optimize roster for remaining draft picks."""
    config = get_roster_config()
    current = config["data"]["current_season"]
    seasons = list(range(current - seasons_back, current + 1))

    data = load_all_data(seasons)
    seasonal = clean_seasonal_stats(data["seasonal"], min_games=config["data"]["min_games"])
    roster = clean_roster_info(data["roster"])
    team = clean_team_stats(data["team"])
    ol = clean_ol_metrics(data["ol"])

    df = build_feature_matrix(seasonal, roster, team, ol)
    df = add_fantasy_points_to_df(df, format=scoring_format)

    pipeline = PositionPipeline(models=[RidgeModel(), RandomForestModel(), XGBoostModel()])
    pipeline.validate_all(df, min_train_seasons=3)
    pipeline.train_final(df)

    projections = pipeline.predict(df, target_season=current)
    if projections.empty:
        click.echo("No projections generated.")
        return

    drafted_list = [p.strip() for p in drafted.split(",") if p.strip()] if drafted else []
    remaining = picks or (sum(config["roster_slots"].values()) - len(drafted_list))

    result = optimize_roster(
        projections, drafted_players=drafted_list,
        remaining_picks=remaining, scoring_format=scoring_format,
    )

    click.echo(f"\n=== Optimized Roster ({scoring_format}) ===")
    for _, row in result.iterrows():
        click.echo(f"  {row['roster_slot']:8s} {row.get('position', '?'):3s} {row.get('player_name', row.get('player_id', '?')):20s} {row['projected_points']:.1f} pts")
    click.echo(f"\nTotal projected points: {result['projected_points'].sum():.1f}")


if __name__ == "__main__":
    cli()

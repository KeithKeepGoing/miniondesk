"""CLI entry point for MinionDesk."""
import asyncio
import click
from rich.console import Console

from miniondesk import __version__

console = Console()


@click.group()
@click.version_option(__version__, prog_name="MinionDesk")
def cli():
    """MinionDesk — Enterprise AI assistant framework."""


@cli.command()
@click.option("--config", default=".env", help="Path to .env config file")
def start(config: str):
    """Start MinionDesk host."""
    from dotenv import load_dotenv
    load_dotenv(config)
    console.print("[bold green]🚀 Starting MinionDesk...[/bold green]")
    from miniondesk.host.main import run_host
    asyncio.run(run_host())


@cli.command()
def setup():
    """Run interactive setup wizard."""
    from setup.setup import run_setup
    asyncio.run(run_setup())


@cli.command()
def check():
    """Check system requirements and configuration."""
    from setup.setup import run_check
    asyncio.run(run_check())


if __name__ == "__main__":
    cli()

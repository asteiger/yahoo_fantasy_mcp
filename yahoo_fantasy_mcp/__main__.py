"""Entry point for running the Yahoo Fantasy MCP server."""

import argparse
import asyncio
import json
import logging
import os
import sys
from getpass import getpass
from pathlib import Path

from yahoo_oauth import OAuth2

from .server import create_server
from .stdio_transport import graceful_stdio_server
from .tools import YahooFantasyTools

logger = logging.getLogger(__name__)

async def run_server(
    client_id: str = None,
    client_secret: str = None,
    oauth2_file: str = None
):
    """Run the MCP server with stdio transport.

    Args:
        client_id: Yahoo API client ID (for env var auth)
        client_secret: Yahoo API client secret (for env var auth)
        oauth2_file: Path to oauth2.json file (alternative auth method)
    """
    server_task = None
    try:
        async with graceful_stdio_server() as (read_stream, write_stream):
            server = create_server(
                client_id=client_id,
                client_secret=client_secret,
                oauth2_file=oauth2_file
            )
            server_task = asyncio.create_task(
                server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options()
                )
            )
            await server_task
    except asyncio.CancelledError:
        logger.info("Server shutdown requested")
        if server_task and not server_task.done():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
        # Re-raise to ensure cleanup continues.
        raise
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        if server_task and not server_task.done():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
        raise
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


def list_available_leagues(
    client_id: str = None,
    client_secret: str = None,
    oauth2_file: str = None,
    title: str = "YAHOO_LEAGUE_ID not set - Listing available leagues"
):
    """List all leagues the user is part of to help with setup.

    Args:
        client_id: Yahoo API client ID (for env var auth)
        client_secret: Yahoo API client secret (for env var auth)
        oauth2_file: Path to oauth2.json file (alternative auth method)
        title: Banner printed above the league list
    """
    print("\n" + "="*60, file=sys.stderr)
    print(title, file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)

    try:
        tools = YahooFantasyTools(
            client_id=client_id,
            client_secret=client_secret,
            oauth2_file=oauth2_file
        )

        game_codes = ['nfl', 'mlb', 'nba', 'nhl']
        all_leagues = []

        for game_code in game_codes:
            print(f"Checking {game_code.upper()} leagues...", file=sys.stderr)
            result = tools.get_all_leagues(game_code=game_code)

            if result.get('leagues'):
                all_leagues.extend(result['leagues'])

        if all_leagues:
            print("\nFound the following leagues:\n", file=sys.stderr)
            for i, league in enumerate(all_leagues, 1):
                print(f"{i}. [{league['game_code'].upper()} {league['year']}] {league['name']}", file=sys.stderr)
                print(f"   League ID: {league['league_id']}", file=sys.stderr)
                print("", file=sys.stderr)

            print("\nTo use one of these leagues, set the YAHOO_LEAGUE_ID environment variable:", file=sys.stderr)
            print("\n  export YAHOO_LEAGUE_ID=<league_id>", file=sys.stderr)
            print("\nFor example:", file=sys.stderr)
            if all_leagues:
                print(f"  export YAHOO_LEAGUE_ID={all_leagues[0]['league_id']}", file=sys.stderr)
        else:
            print("\nNo leagues found. You may not be part of any active leagues.", file=sys.stderr)
            print("Please join a league on Yahoo Fantasy Sports first.", file=sys.stderr)

        print("\n" + "="*60 + "\n", file=sys.stderr)

    except Exception as e:
        print(f"\nError listing leagues: {e}", file=sys.stderr)
        print("Please check your credentials and try again.\n", file=sys.stderr)


def _consumer_credentials(oauth2_file: Path) -> tuple[str, str]:
    """Find the Yahoo app credentials in the environment, an existing file, or by prompting."""
    client_id = os.getenv("YAHOO_CLIENT_ID")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret

    # Re-authorizing reuses the app credentials already saved in the file.
    if oauth2_file.exists():
        try:
            data = json.loads(oauth2_file.read_text())
        except (OSError, ValueError):
            data = {}
        if data.get("consumer_key") and data.get("consumer_secret"):
            return data["consumer_key"], data["consumer_secret"]

    print("Enter your Yahoo app credentials (from https://developer.yahoo.com/apps/).")
    client_id = input("Client ID (consumer key): ").strip()
    client_secret = getpass("Client secret (consumer secret): ").strip()
    return client_id, client_secret


def run_auth(oauth2_file: Path) -> int:
    """Authorize with Yahoo interactively and save the tokens to oauth2_file.

    Returns:
        Process exit code.
    """
    # yahoo_oauth logs the authorization URL and tokens at DEBUG.
    logging.getLogger("yahoo_oauth").setLevel(logging.WARNING)

    client_id, client_secret = _consumer_credentials(oauth2_file)
    if not client_id or not client_secret:
        print("Error: a client ID and client secret are required.", file=sys.stderr)
        return 1

    print(
        "\nOpen the authorization URL below, sign in to Yahoo, approve access, "
        "and paste the code Yahoo shows you.\n"
    )
    try:
        # Tokens are written below, only once the flow succeeds, so a failed
        # attempt never clobbers a working oauth2.json.
        oauth = OAuth2(client_id, client_secret, browser_callback=False, store_file=False)
    except KeyError:
        # yahoo_oauth indexes the token response directly, so a rejected
        # request surfaces as a missing 'access_token' key.
        print(
            "\nError: Yahoo rejected the authorization. Check the client ID, "
            "client secret, and code, then try again.",
            file=sys.stderr
        )
        return 1
    except Exception as e:
        print(f"\nError: authorization failed: {e}", file=sys.stderr)
        return 1

    credentials = {
        "consumer_key": client_id,
        "consumer_secret": client_secret,
        "access_token": oauth.access_token,
        "refresh_token": oauth.refresh_token,
        "token_type": oauth.token_type,
        "token_time": oauth.token_time,
    }
    try:
        oauth2_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(oauth2_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(credentials, f, indent=4, sort_keys=True)
    except OSError as e:
        print(f"Error: could not write {oauth2_file}: {e}", file=sys.stderr)
        return 1

    print(f"\nSaved credentials to {oauth2_file}")
    list_available_leagues(oauth2_file=str(oauth2_file), title="Authorized - Listing available leagues")
    return 0


def main():
    """Run the MCP server."""
    parser = argparse.ArgumentParser(description="Yahoo Fantasy MCP Server")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["serve", "auth"],
        default="serve",
        help="'serve' runs the MCP server (default); 'auth' authorizes with Yahoo and writes the oauth2 file"
    )
    parser.add_argument(
        "--oauth2-file",
        type=str,
        default="oauth2.json",
        help="Path to oauth2.json file (default: oauth2.json)"
    )
    args = parser.parse_args()

    # Check if oauth2.json file exists.
    oauth2_file = Path(args.oauth2_file)

    if args.command == "auth":
        sys.exit(run_auth(oauth2_file))

    # Determine authentication method.
    if oauth2_file.exists():
        print(f"Using OAuth credentials from {oauth2_file}", file=sys.stderr)
        auth_kwargs = {"oauth2_file": str(oauth2_file)}
    else:
        # Check for environment variables.
        client_id = os.getenv("YAHOO_CLIENT_ID")
        client_secret = os.getenv("YAHOO_CLIENT_SECRET")

        if not client_id or not client_secret:
            print(
                f"Error: {oauth2_file} not found and YAHOO_CLIENT_ID/YAHOO_CLIENT_SECRET "
                "environment variables are not set",
                file=sys.stderr
            )
            print("\nPlease either:", file=sys.stderr)
            print(f"  1. Run 'yahoo-fantasy-mcp auth' to create {oauth2_file}", file=sys.stderr)
            print("  2. Set YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET environment variables", file=sys.stderr)
            sys.exit(1)

        print("Using OAuth credentials from environment variables", file=sys.stderr)
        auth_kwargs = {"client_id": client_id, "client_secret": client_secret}

    # Check if league ID is set.
    league_id = os.getenv("YAHOO_LEAGUE_ID")
    if not league_id:
        list_available_leagues(**auth_kwargs)
        sys.exit(0)

    print(f"Using league ID: {league_id}", file=sys.stderr)

    try:
        asyncio.run(run_server(**auth_kwargs))
    except KeyboardInterrupt:
        print("\nServer stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()

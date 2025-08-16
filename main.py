#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "python-dotenv>=1.1.1",
#     "requests>=2.32.0",
#     "rich>=14.1.0",
#     "typer>=0.16.0",
#     "webexpythonsdk>=2.0.5",
# ]
# ///
"""Webex Room ID Fetcher - Find Webex room IDs by name."""

import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from webexpythonsdk import WebexAPI

# Load environment variables
load_dotenv()

console = Console()
app = typer.Typer(help="Find Webex room IDs by room name")

# Configuration
TOKENS_FILE = Path.home() / ".webex_tokens.json"
REDIRECT_PORT = 6001
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback from Webex."""

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET request with authorization code."""
        if self.path.startswith("/callback"):
            # Extract authorization code from URL
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)

            if "code" in query_params:
                # Store the authorization code
                self.server.auth_code = query_params["code"][0]

                # Send success response
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                success_html = """
                <html>
                <body>
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                <script>
                setTimeout(function() { window.close(); }, 2000);
                </script>
                </body>
                </html>
                """
                self.wfile.write(success_html.encode())
            else:
                # Send error response
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>Authentication Failed</h1>"
                    b"<p>No authorization code received.</p>"
                )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress server logs."""
        pass


def get_oauth_tokens() -> dict | None:
    """Get OAuth tokens, handling the full OAuth flow if necessary."""
    # Check for existing valid tokens
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE) as f:
                tokens = json.load(f)
            return tokens
        except (json.JSONDecodeError, KeyError):
            console.print(
                "[yellow]Existing tokens file is invalid, will re-authenticate[/yellow]"
            )

    # Get OAuth credentials from environment
    client_id = os.getenv("WEBEX_CLIENT_ID")
    client_secret = os.getenv("WEBEX_CLIENT_SECRET")

    if not client_id or not client_secret:
        console.print(
            Panel.fit(
                "[red]Missing OAuth credentials![/red]\n\n"
                "Please set the following environment variables:\n"
                "• WEBEX_CLIENT_ID\n"
                "• WEBEX_CLIENT_SECRET\n\n"
                "Get these by creating a Webex Integration at:\n"
                "https://developer.webex.com/my-apps\n\n"
                "Required scopes: spark:rooms_read",
                title="Configuration Error",
            )
        )
        raise typer.Exit(1)

    # Start local server for OAuth callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
    server.auth_code = None

    def run_server() -> None:
        server.handle_request()  # Handle one request then stop

    server_thread = Thread(target=run_server)
    server_thread.start()

    # Build OAuth authorization URL
    from urllib.parse import quote_plus

    scopes = "spark:rooms_read"
    auth_url = (
        f"https://webexapis.com/v1/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={quote_plus(REDIRECT_URI)}&"
        f"scope={quote_plus(scopes)}"
    )

    console.print(
        Panel.fit(
            f"[bold blue]Opening browser for Webex authentication...[/bold blue]\n\n"
            f"If the browser doesn't open automatically, visit:\n"
            f"[link]{auth_url}[/link]",
            title="OAuth Authentication",
        )
    )

    # Open browser for authentication
    webbrowser.open(auth_url)

    # Wait for callback
    server_thread.join()

    if not server.auth_code:
        console.print(
            "[red]Authentication failed - no authorization code received[/red]"
        )
        raise typer.Exit(1)

    # Exchange authorization code for tokens
    import requests

    token_url = "https://webexapis.com/v1/access_token"
    token_data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": server.auth_code,
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(token_url, data=token_data)
    if response.status_code != 200:
        console.print(f"[red]Token exchange failed: {response.text}[/red]")
        raise typer.Exit(1)

    tokens = response.json()

    # Save tokens
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    console.print("[green]✓ Authentication successful! Tokens saved.[/green]")
    return tokens


def get_webex_api() -> WebexAPI:
    """Get authenticated Webex API client."""
    tokens = get_oauth_tokens()
    if not tokens:
        raise typer.Exit(1)

    return WebexAPI(access_token=tokens["access_token"])


def _debug_fetch_start(max_rooms: int, debug: bool) -> float:
    """Log debug information at the start of fetch."""
    import time

    if debug:
        console.print(
            f"[dim]DEBUG: Starting efficient rooms fetch with max={max_rooms}[/dim]"
        )
        console.print(
            "[dim]DEBUG: Using sortBy=lastactivity for recent rooms first[/dim]"
        )
        return time.time()
    return 0.0


def _debug_fetch_end(rooms_list: list, start_time: float, debug: bool) -> None:
    """Log debug information at the end of fetch."""
    import time

    if debug:
        end_time = time.time()
        console.print(
            f"[dim]DEBUG: Fetch completed in {end_time - start_time:.2f} seconds[/dim]"  # noqa: E501
        )
        console.print(f"[dim]DEBUG: Retrieved {len(rooms_list)} rooms[/dim]")
        if rooms_list:
            console.print(f"[dim]DEBUG: First room: {rooms_list[0].title}[/dim]")


def fetch_rooms_efficiently(
    api: WebexAPI, max_rooms: int = 100, debug: bool = False
) -> list:
    """Fetch rooms efficiently using webex-summarizer patterns."""
    start_time = _debug_fetch_start(max_rooms, debug)

    try:
        # Use webex-summarizer pattern: sortBy + direct iteration
        rooms_iterator = api.rooms.list(max=max_rooms, sortBy="lastactivity")

        if debug:
            console.print(
                "[dim]DEBUG: Got iterator, iterating directly (no list conversion)[/dim]"  # noqa: E501
            )

        rooms_list = []
        processed_count = 0

        # Iterate directly like webex-summarizer does
        for room in rooms_iterator:
            if debug and processed_count < 3:  # Log first few for debugging
                console.print(
                    f"[dim]DEBUG: Processing room: {room.title[:30]}...[/dim]"
                )

            rooms_list.append(room)
            processed_count += 1

            # Optional: Break early if we have enough (though max should handle this)
            if len(rooms_list) >= max_rooms:
                break

        _debug_fetch_end(rooms_list, start_time, debug)
        return rooms_list

    except Exception as e:
        if debug:
            console.print(f"[dim]DEBUG: Exception occurred: {type(e).__name__}[/dim]")
            console.print(f"[dim]DEBUG: Exception details: {str(e)}[/dim]")
        console.print(f"[red]Error during API call: {type(e).__name__}: {e}[/red]")
        raise


def search_rooms(rooms: list, room_name: str, exact_match: bool) -> list:
    """Search for rooms matching the given name."""
    if exact_match:
        return [room for room in rooms if room.title == room_name]
    else:
        room_name_lower = room_name.lower()
        return [room for room in rooms if room_name_lower in room.title.lower()]


def display_found_rooms(found_rooms: list) -> None:
    """Display found rooms to the user."""
    if len(found_rooms) == 1:
        room = found_rooms[0]
        console.print(f"[green]✓ Found room: {room.title}[/green]")
        rprint(f"[bold]{room.id}[/bold]")
    else:
        console.print(f"[yellow]Found {len(found_rooms)} matching rooms:[/yellow]")
        for room in found_rooms:
            rprint(f"[bold]{room.title}[/bold]: {room.id}")


def handle_no_matches(room_name: str, rooms: list, list_all: bool) -> None:
    """Handle the case when no rooms match the search criteria."""
    console.print(f"[red]No room found matching '{room_name}'[/red]")

    if list_all:
        console.print("\n[blue]All available rooms:[/blue]")
        for room in sorted(rooms, key=lambda x: x.title):
            rprint(f"• {room.title}")
    else:
        console.print("\n[dim]Use --list to see all available rooms[/dim]")

    raise typer.Exit(1)


@app.command()
def find(
    room_name: str = typer.Argument(..., help="Name of the Webex room to find"),
    exact_match: bool = typer.Option(
        False, "--exact", "-e", help="Require exact name match (case-sensitive)"
    ),
    list_all: bool = typer.Option(
        False, "--list", "-l", help="List all rooms if no match found"
    ),
) -> None:
    """Find a Webex room ID by room name."""
    try:
        api = get_webex_api()

        # Get rooms (fetch more for searching)
        with console.status("[blue]Fetching rooms...[/blue]", spinner="arc"):
            rooms = fetch_rooms_efficiently(api, max_rooms=500, debug=False)

        if not rooms:
            console.print("[yellow]No rooms found[/yellow]")
            raise typer.Exit(0)

        console.print(f"[green]✓[/green] Fetched {len(rooms)} rooms")

        # Search for matching rooms
        found_rooms = search_rooms(rooms, room_name, exact_match)

        if found_rooms:
            display_found_rooms(found_rooms)
        else:
            handle_no_matches(room_name, rooms, list_all)

    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            console.print("[red]Authentication failed. Removing stored tokens...[/red]")
            if TOKENS_FILE.exists():
                TOKENS_FILE.unlink()
            console.print("Please run the command again to re-authenticate.")
            raise typer.Exit(1) from None
        else:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1) from None


@app.command()
def test_connectivity() -> None:
    """Test connectivity to Webex API and diagnose potential issues."""
    import requests

    console.print("[blue]Testing Webex API connectivity...[/blue]")

    try:
        # Test basic connectivity to Webex API
        with console.status(
            "[blue]Testing network connectivity...[/blue]", spinner="arc"
        ):
            response = requests.get("https://webexapis.com/v1/people/me", timeout=10)

        if response.status_code == 401:
            console.print(
                "[yellow]✓ Network connectivity OK (401 expected without auth)[/yellow]"
            )
        else:
            console.print(
                f"[yellow]✓ Network connectivity OK (status: {response.status_code})[/yellow]"  # noqa: E501
            )

        # Test authentication
        try:
            api = get_webex_api()
            console.print("[green]✓ Authentication tokens loaded[/green]")

            # Debug: Check token info
            tokens = get_oauth_tokens()
            if tokens and "access_token" in tokens:
                token_preview = (
                    tokens["access_token"][:20] + "..."
                    if len(tokens["access_token"]) > 20
                    else tokens["access_token"]
                )
                console.print(f"[dim]Debug: Token preview: {token_preview}[/dim]")
                if "scope" in tokens:
                    console.print(f"[dim]Debug: Token scopes: {tokens['scope']}[/dim]")

            # Test rooms API directly (skip people.me() which needs different scope)
            # Test rooms API specifically
            console.print("\n[blue]Testing rooms API specifically...[/blue]")
            with console.status(
                "[blue]Testing rooms.list() call...[/blue]", spinner="arc"
            ):
                try:
                    console.print(
                        "[dim]DEBUG: About to call api.rooms.list(max=1)[/dim]"
                    )
                    rooms_iterator = api.rooms.list(max=1)
                    console.print(
                        "[dim]DEBUG: Got iterator, converting to list...[/dim]"
                    )
                    rooms = list(rooms_iterator)  # Try to get just 1 room
                    console.print(
                        f"[green]✓ Rooms API working! Found {len(rooms)} room(s)[/green]"  # noqa: E501
                    )
                except Exception as rooms_error:
                    console.print(f"[red]✗ Rooms API failed: {rooms_error}[/red]")
                    console.print("\n[yellow]Possible solutions:[/yellow]")
                    console.print(
                        "  1. Check your Webex integration has 'spark:rooms_read' scope"
                    )
                    console.print(
                        "  2. Ensure your Webex account has the right license"
                    )
                    console.print(
                        "  3. Verify you're a member of at least one Webex space"
                    )
                    console.print("  4. Try recreating your Webex integration at:")
                    console.print("     https://developer.webex.com/my-apps")

        except Exception as e:
            console.print(f"[red]✗ Authentication failed: {e}[/red]")
            console.print("[yellow]Try running: ./main.py auth[/yellow]")

    except requests.exceptions.RequestException as e:
        console.print(f"[red]✗ Network connectivity failed: {e}[/red]")
        console.print(
            "[yellow]Check your internet connection and firewall settings[/yellow]"
        )
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {e}[/red]")


@app.command()
def auth() -> None:
    """Authenticate with Webex (re-authenticate if already authenticated)."""
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()
        console.print("[blue]Removed existing authentication[/blue]")

    try:
        get_oauth_tokens()
        console.print("[green]✓ Authentication complete![/green]")
    except Exception as e:
        console.print(f"[red]Authentication failed: {e}[/red]")
        raise typer.Exit(1) from None


def format_room_activity_date(activity_date: object) -> str:
    """Format room activity date for display."""
    if not activity_date:
        return ""

    if hasattr(activity_date, "strftime"):
        return activity_date.strftime("%Y-%m-%d %H:%M")
    else:
        return str(activity_date)[:19]  # Truncate timestamp


def display_rooms_with_activity(rooms: list) -> None:
    """Display rooms with their activity dates."""
    for room in rooms:
        activity_date = room.lastActivity or room.created
        if activity_date:
            activity_str = format_room_activity_date(activity_date)
            rprint(f"[bold]{room.title}[/bold]: {room.id} [dim]({activity_str})[/dim]")
        else:
            rprint(f"[bold]{room.title}[/bold]: {room.id}")


def get_sorted_and_limited_rooms(
    all_rooms: list, max_rooms: int
) -> tuple[list, int, int]:
    """Sort rooms by activity and apply limit."""
    # Sort by lastActivity (most recent first), with fallback to created date
    sorted_rooms = sorted(
        all_rooms, key=lambda x: x.lastActivity or x.created, reverse=True
    )

    # Apply limit
    limited_rooms = sorted_rooms[:max_rooms]
    return limited_rooms, len(all_rooms), len(limited_rooms)


@app.command()
def list_rooms(
    max_rooms: int = typer.Option(
        100,
        envvar="WEBEX_MAX_ROOMS",
        help="Maximum number of rooms to display (default: 100). "
        "Can also be set via WEBEX_MAX_ROOMS environment variable.",
    ),
    timeout: int = typer.Option(
        30,
        "--timeout",
        help="API request timeout in seconds (default: 30).",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug output for troubleshooting.",
    ),
) -> None:
    """List Webex rooms you're a member of, sorted by most recent activity."""
    try:
        api = get_webex_api()

        if debug:
            console.print(f"[dim]Debug: Using timeout of {timeout} seconds[/dim]")
            console.print(
                f"[dim]Debug: Webex base URL: {api.base_url if hasattr(api, 'base_url') else 'Unknown'}[/dim]"  # noqa: E501
            )

        with console.status("[blue]Fetching rooms...[/blue]", spinner="arc"):
            all_rooms = fetch_rooms_efficiently(api, max_rooms=max_rooms, debug=debug)

        if not all_rooms:
            console.print("[yellow]No rooms found[/yellow]")
            return

        console.print(f"[green]✓[/green] Fetched {len(all_rooms)} rooms")

        # Sort by activity (since we fetched exactly max_rooms from API)
        with console.status("[blue]Sorting by activity...[/blue]", spinner="line"):
            # Sort the fetched rooms by activity
            sorted_rooms = sorted(
                all_rooms, key=lambda x: x.lastActivity or x.created, reverse=True
            )

        # total_count = len(all_rooms)  # Available but not needed
        displayed_count = len(sorted_rooms)

        # Display summary
        console.print(
            f"[green]Showing {displayed_count} most recent rooms "
            f"(API limit: {max_rooms}):[/green]\n"
        )

        # Display rooms
        display_rooms_with_activity(sorted_rooms)

    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            console.print(
                "[red]Authentication failed. Please run 'auth' command first.[/red]"
            )
            raise typer.Exit(1) from None
        else:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1) from None


if __name__ == "__main__":
    app()

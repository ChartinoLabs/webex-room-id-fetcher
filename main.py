#!/usr/bin/env -S uv run python
"""Webex Room ID Fetcher - Find Webex room IDs by name."""

import json
import os
import sys
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
    
    def do_GET(self) -> None:
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
                self.wfile.write(b"<h1>Authentication Failed</h1><p>No authorization code received.</p>")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format: str, *args) -> None:
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
            console.print("[yellow]Existing tokens file is invalid, will re-authenticate[/yellow]")
    
    # Get OAuth credentials from environment
    client_id = os.getenv("WEBEX_CLIENT_ID")
    client_secret = os.getenv("WEBEX_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        console.print(Panel.fit(
            "[red]Missing OAuth credentials![/red]\n\n"
            "Please set the following environment variables:\n"
            "• WEBEX_CLIENT_ID\n"
            "• WEBEX_CLIENT_SECRET\n\n"
            "Get these by creating a Webex Integration at:\n"
            "https://developer.webex.com/my-apps\n\n"
            "Required scopes: spark:rooms_read",
            title="Configuration Error"
        ))
        raise typer.Exit(1)
    
    # Start local server for OAuth callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
    server.auth_code = None
    
    def run_server():
        server.handle_request()  # Handle one request then stop
    
    server_thread = Thread(target=run_server)
    server_thread.start()
    
    # Build OAuth authorization URL
    scopes = "spark:rooms_read"
    auth_url = (
        f"https://webexapis.com/v1/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={REDIRECT_URI}&"
        f"scope={scopes}"
    )
    
    console.print(Panel.fit(
        f"[bold blue]Opening browser for Webex authentication...[/bold blue]\n\n"
        f"If the browser doesn't open automatically, visit:\n"
        f"[link]{auth_url}[/link]",
        title="OAuth Authentication"
    ))
    
    # Open browser for authentication
    webbrowser.open(auth_url)
    
    # Wait for callback
    server_thread.join()
    
    if not server.auth_code:
        console.print("[red]Authentication failed - no authorization code received[/red]")
        raise typer.Exit(1)
    
    # Exchange authorization code for tokens
    import requests
    
    token_url = "https://webexapis.com/v1/access_token"
    token_data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": server.auth_code,
        "redirect_uri": REDIRECT_URI
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


@app.command()
def find(
    room_name: str = typer.Argument(..., help="Name of the Webex room to find"),
    exact_match: bool = typer.Option(False, "--exact", "-e", help="Require exact name match (case-sensitive)"),
    list_all: bool = typer.Option(False, "--list", "-l", help="List all rooms if no match found")
) -> None:
    """Find a Webex room ID by room name."""
    try:
        api = get_webex_api()
        
        # Get all rooms
        console.print("[blue]Fetching rooms...[/blue]")
        rooms = list(api.rooms.list())
        
        if not rooms:
            console.print("[yellow]No rooms found[/yellow]")
            raise typer.Exit(0)
        
        # Search for matching room
        found_rooms = []
        
        if exact_match:
            found_rooms = [room for room in rooms if room.title == room_name]
        else:
            # Case-insensitive partial match
            room_name_lower = room_name.lower()
            found_rooms = [room for room in rooms if room_name_lower in room.title.lower()]
        
        if found_rooms:
            if len(found_rooms) == 1:
                room = found_rooms[0]
                console.print(f"[green]✓ Found room: {room.title}[/green]")
                rprint(f"[bold]{room.id}[/bold]")
            else:
                console.print(f"[yellow]Found {len(found_rooms)} matching rooms:[/yellow]")
                for room in found_rooms:
                    rprint(f"[bold]{room.title}[/bold]: {room.id}")
        else:
            console.print(f"[red]No room found matching '{room_name}'[/red]")
            
            if list_all:
                console.print("\n[blue]All available rooms:[/blue]")
                for room in sorted(rooms, key=lambda x: x.title):
                    rprint(f"• {room.title}")
            else:
                console.print("\n[dim]Use --list to see all available rooms[/dim]")
            
            raise typer.Exit(1)
    
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            console.print("[red]Authentication failed. Removing stored tokens...[/red]")
            if TOKENS_FILE.exists():
                TOKENS_FILE.unlink()
            console.print("Please run the command again to re-authenticate.")
            raise typer.Exit(1)
        else:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


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
        raise typer.Exit(1)


@app.command()
def list_rooms() -> None:
    """List all Webex rooms you're a member of."""
    try:
        api = get_webex_api()
        
        console.print("[blue]Fetching all rooms...[/blue]")
        rooms = list(api.rooms.list())
        
        if not rooms:
            console.print("[yellow]No rooms found[/yellow]")
            return
        
        console.print(f"[green]Found {len(rooms)} rooms:[/green]\n")
        for room in sorted(rooms, key=lambda x: x.title):
            rprint(f"[bold]{room.title}[/bold]: {room.id}")
    
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            console.print("[red]Authentication failed. Please run 'auth' command first.[/red]")
            raise typer.Exit(1)
        else:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()

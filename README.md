# Webex Room ID Fetcher

A command-line tool to quickly find Webex room/space IDs by name using the Webex API. Perfect for automating workflows that need to interact with specific Webex spaces.

## Features

- **OAuth Authentication**: Secure authentication with Webex using OAuth 2.0 flow
- **Flexible Search**: Find rooms by exact or partial name matching
- **UV Integration**: Uses UV for dependency management with direct script execution
- **Token Caching**: Automatically handles and caches authentication tokens
- **Rich CLI**: Beautiful command-line interface with colored output
- **Multiple Commands**: Find rooms, list all rooms, or re-authenticate

## Prerequisites

- Python 3.13 or higher
- UV dependency management system
- A Webex account

## Installation

First, clone this repository:

```bash
git clone <repository-url>
cd webex-room-id-fetcher
```

Then, install dependencies using UV:

```bash
uv sync
```

Then, set up Webex OAuth credentials:

- Go to [Webex Developer Portal](https://developer.webex.com/my-apps)
- Click "Create a New App" → "Create an Integration"
- Fill in the details:
    - **Integration Name**: Your app name (e.g., "Room ID Fetcher")
    - **Description**: Brief description of your tool
    - **Redirect URI**: `http://localhost:6001/callback`
    - **Scopes**: `spark:rooms_read`
- Copy the Client ID and Client Secret
- Create a `.env` file in the project root:

```bash
# Webex OAuth Configuration
WEBEX_CLIENT_ID=your_client_id_here
WEBEX_CLIENT_SECRET=your_client_secret_here
```

Then, make the script executable:

```bash
chmod +x main.py
```

## Usage

### First Run - Authentication

On first use, authenticate with Webex:

```bash
./main.py auth
```

This will open your browser for Webex authentication. After authorizing, tokens will be cached for future use.

### Find a Room ID

```bash
# Find room by partial name (case-insensitive)
./main.py find "Project Alpha"

# Find room by exact name (case-sensitive)
./main.py find "Project Alpha Team" --exact

# Find room and list all rooms if no match found
./main.py find "Alpha" --list
```

### List All Rooms

```bash
./main.py list-rooms
```

### Re-authenticate

```bash
./main.py auth
```

## Examples

```bash
# Find a room named "Marketing Team"
$ ./main.py find "Marketing Team"
✓ Found room: Marketing Team
Y2lzY29zcGFyazovL3VzL1JPT00vYWJjZGVmZ2g=

# Find rooms containing "dev" (shows multiple matches)
$ ./main.py find "dev"
Found 3 matching rooms:
Development Team: Y2lzY29zcGFyazovL3VzL1JPT00vZGV2dGVhbQ==
DevOps: Y2lzY29zcGFyazovL3VzL1JPT00vZGV2b3Bz
Mobile Dev: Y2lzY29zcGFyazovL3VzL1JPT00vbW9iaWxlZGV2

# List all available rooms
$ ./main.py list-rooms
Found 15 rooms:

Engineering: Y2lzY29zcGFyazovL3VzL1JPT00vZW5naW5lZXJpbmc=
Marketing Team: Y2lzY29zcGFyazovL3VzL1JPT00vbWFya2V0aW5n
...
```

## Integration with Shell Aliases

Add to your `.zshrc` or `.bashrc`:

```bash
alias webex-room-id="/path/to/webex-room-id-fetcher/main.py find"
alias webex-rooms="/path/to/webex-room-id-fetcher/main.py list-rooms"
```

Then use from anywhere:

```bash
webex-room-id "My Room Name"
```

## Command Reference

### `find <room_name>`

Find a Webex room ID by name.

**Arguments:**

- `room_name`: Name or partial name of the room to find

**Options:**

- `--exact, -e`: Require exact name match (case-sensitive)
- `--list, -l`: List all rooms if no match found

### `list-rooms`

List all Webex rooms you're a member of with their IDs.

### `auth`

Authenticate with Webex or re-authenticate if already authenticated.

## Troubleshooting

### Authentication Issues

If you get authentication errors:

1. Run `./main.py auth` to re-authenticate
2. Check that your Client ID and Client Secret are correct
3. Ensure the redirect URI in your Webex integration is exactly: `http://localhost:6001/callback`

### Room Not Found

If a room isn't found:

- Try partial matching without `--exact`
- Use `--list` to see all available rooms
- Check that you're a member of the room you're searching for

### Permission Issues

Make sure the script is executable:

```bash
chmod +x main.py
```

## Technical Details

- **Authentication**: Uses OAuth 2.0 authorization code flow
- **Token Storage**: Tokens are cached in `~/.webex_tokens.json`
- **Dependencies**: Managed with UV for reproducible environments
- **API**: Uses the official Webex Python SDK

## Security Notes

- Tokens are stored locally in your home directory
- The `.env` file and token file are ignored by git
- OAuth flow uses localhost redirect for security

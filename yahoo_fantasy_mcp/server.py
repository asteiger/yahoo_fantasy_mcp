"""Main MCP server implementation for Yahoo Fantasy API."""

from __future__ import annotations

import logging
import os
from typing import Optional

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    Resource,
    TextContent,
    Tool,
    ToolAnnotations,
)

from . import __version__
from .tools import YahooFantasyTools

logger = logging.getLogger(__name__)

_YAHOO_LEAGUE_ENV = "YAHOO_LEAGUE_ID"
_LEAGUE_RESOURCE_URI = "resource://yahoo-fantasy/league-id"


def _league_resource_description(league_id: str | None) -> str:
    """Describe the league resource based on whether a league ID is configured."""
    if league_id:
        return f"Yahoo Fantasy league configured via {_YAHOO_LEAGUE_ENV}: {league_id}"
    return f"{_YAHOO_LEAGUE_ENV} is not set; no league is configured for this server."


def _build_league_resource(league_id: str | None) -> Resource:
    """Build the Resource metadata for the configured league ID."""
    meta_payload = {"league_id": league_id} if league_id else None
    size = len(league_id) if league_id else None
    return Resource(
        uri=_LEAGUE_RESOURCE_URI,
        name="yahoo-league-id",
        title="Yahoo Fantasy League ID",
        description=_league_resource_description(league_id),
        mimeType="application/json",
        size=size,
        _meta=meta_payload,
    )


def _list_league_resources(league_id: str | None = None) -> list[Resource]:
    """Return the league resource list, defaulting to the configured environment var."""
    if league_id is None:
        league_id = os.getenv(_YAHOO_LEAGUE_ENV)
    return [_build_league_resource(league_id)]


_READ_ONLY_ANNOTATIONS = ToolAnnotations(read_only_hint=True, open_world_hint=True)

_WRITE_WARNING = "This modifies the team on Yahoo! Fantasy."

_TEAM_KEY_PROPERTY = {
    "type": "string",
    "description": "The team key to modify (use get_team_key to find the user's team)"
}

_TRADE_NOTE_PROPERTY = {
    "type": "string",
    "description": "Optional note to include with the trade"
}


def _write_annotations(destructive: bool, idempotent: bool = False) -> ToolAnnotations:
    """Build annotations for a tool that modifies league state."""
    return ToolAnnotations(
        read_only_hint=False,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=True,
    )


_WRITE_TOOLS = [
    Tool(
        name="change_positions",
        description=(
            "Change the lineup positions of one or more players on a team, e.g. "
            "move a player to the bench or into a starting slot. " + _WRITE_WARNING
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "players": {
                    "type": "array",
                    "description": "Players to move and their new positions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "player_id": {
                                "type": "integer",
                                "description": "Yahoo! player ID"
                            },
                            "selected_position": {
                                "type": "string",
                                "description": "New position, e.g. 'BN', 'QB', 'C', 'IL'"
                            }
                        },
                        "required": ["player_id", "selected_position"]
                    },
                    "minItems": 1
                },
                "date": {
                    "type": "string",
                    "description": "Day the change takes effect (YYYY-MM-DD). Use for daily leagues (MLB, NBA, NHL)."
                },
                "week": {
                    "type": "integer",
                    "description": (
                        "Week the change takes effect. Use for weekly leagues (NFL). "
                        "Specify exactly one of date or week."
                    )
                }
            },
            "required": ["team_key", "players"]
        },
        annotations=_write_annotations(destructive=False, idempotent=True),
    ),
    Tool(
        name="add_player",
        description="Add a free agent to a team. " + _WRITE_WARNING,
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to add"
                }
            },
            "required": ["team_key", "player_id"]
        },
        annotations=_write_annotations(destructive=False),
    ),
    Tool(
        name="drop_player",
        description="Drop a player from a team. " + _WRITE_WARNING,
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to drop"
                }
            },
            "required": ["team_key", "player_id"]
        },
        annotations=_write_annotations(destructive=True),
    ),
    Tool(
        name="add_and_drop_players",
        description="Add a free agent and drop a player in a single transaction. " + _WRITE_WARNING,
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "add_player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to add"
                },
                "drop_player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to drop"
                }
            },
            "required": ["team_key", "add_player_id", "drop_player_id"]
        },
        annotations=_write_annotations(destructive=True),
    ),
    Tool(
        name="claim_player",
        description="Submit a waiver claim for a player, optionally with a FAAB bid. " + _WRITE_WARNING,
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to claim"
                },
                "faab": {
                    "type": "integer",
                    "description": "FAAB dollars to bid (optional, only for FAAB leagues)"
                }
            },
            "required": ["team_key", "player_id"]
        },
        annotations=_write_annotations(destructive=False),
    ),
    Tool(
        name="claim_and_drop_players",
        description=(
            "Submit a waiver claim for a player and drop another player if the "
            "claim succeeds, optionally with a FAAB bid. " + _WRITE_WARNING
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "add_player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to claim"
                },
                "drop_player_id": {
                    "type": "integer",
                    "description": "Yahoo! player ID of the player to drop"
                },
                "faab": {
                    "type": "integer",
                    "description": "FAAB dollars to bid (optional, only for FAAB leagues)"
                }
            },
            "required": ["team_key", "add_player_id", "drop_player_id"]
        },
        annotations=_write_annotations(destructive=True),
    ),
    Tool(
        name="propose_trade",
        description="Propose a trade to another team. " + _WRITE_WARNING,
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": {
                    "type": "string",
                    "description": "The team key proposing the trade"
                },
                "tradee_team_key": {
                    "type": "string",
                    "description": "The team key of the team receiving the proposal"
                },
                "your_player_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Yahoo! player IDs the proposing team sends"
                },
                "their_player_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Yahoo! player IDs requested from the other team"
                },
                "trade_note": _TRADE_NOTE_PROPERTY
            },
            "required": ["team_key", "tradee_team_key", "your_player_ids", "their_player_ids"]
        },
        annotations=_write_annotations(destructive=False),
    ),
    Tool(
        name="accept_trade",
        description=(
            "Accept a trade proposed to a team (transaction keys come from "
            "get_team_proposed_trades). " + _WRITE_WARNING
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "transaction_key": {
                    "type": "string",
                    "description": "Key of the proposed trade, e.g. '423.l.123456.pt.1'"
                },
                "trade_note": _TRADE_NOTE_PROPERTY
            },
            "required": ["team_key", "transaction_key"]
        },
        annotations=_write_annotations(destructive=True),
    ),
    Tool(
        name="reject_trade",
        description=(
            "Reject a trade proposed to a team (transaction keys come from "
            "get_team_proposed_trades). " + _WRITE_WARNING
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "team_key": _TEAM_KEY_PROPERTY,
                "transaction_key": {
                    "type": "string",
                    "description": "Key of the proposed trade, e.g. '423.l.123456.pt.1'"
                },
                "trade_note": _TRADE_NOTE_PROPERTY
            },
            "required": ["team_key", "transaction_key"]
        },
        annotations=_write_annotations(destructive=True),
    ),
]


def create_server(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    oauth2_file: Optional[str] = None
) -> Server:
    """Create and configure the MCP server.

    Args:
        client_id: Yahoo API client ID (for env var auth)
        client_secret: Yahoo API client secret (for env var auth)
        oauth2_file: Path to oauth2.json file (alternative auth method)

    Returns:
        Configured MCP Server instance
    """
    tools = YahooFantasyTools(
        client_id=client_id,
        client_secret=client_secret,
        oauth2_file=oauth2_file
    )

    async def list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        """List resources exposed by the MCP server."""
        return ListResourcesResult(resources=_list_league_resources())

    async def list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        """List available tools."""
        read_tools = [
            Tool(
                name="get_team_key",
                description="Get the team key for the logged in user's team in a league",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_current_week",
                description="Get the current week number of the league",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_edit_date",
                description="Get the next date when lineups can be edited (roster deadline)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_end_week",
                description="Get the ending week number of the league season",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_matchups",
                description="Get matchup data for a given week (defaults to current week)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        },
                        "week": {
                            "type": "integer",
                            "description": "Week number (optional, defaults to current week)"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_positions",
                description="Get the positions used in the league with their counts and types",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_settings",
                description="Get comprehensive league settings including scoring, playoff, waiver, and trade settings",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_stat_categories",
                description="Get the stat categories tracked in the league with their position types",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_teams",
                description="Get details of all teams in the league including roster management stats and managers",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_transactions",
                description="Get league transactions (adds, drops, trades, commish moves)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        },
                        "tran_types": {
                            "type": "string",
                            "description": "Comma-separated transaction types: add, drop, commish, trade"
                        },
                        "count": {
                            "type": "string",
                            "description": "Number of transactions to retrieve (optional, returns all if not specified)"
                        }
                    },
                    "required": ["league_id", "tran_types"]
                }
            ),
            Tool(
                name="get_league_standings",
                description="Get current standings for a fantasy league",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
            Tool(
                name="get_team_roster",
                description="Get roster for a specific team for a given week or date",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_key": {
                            "type": "string",
                            "description": "The team key to query"
                        },
                        "week": {
                            "type": "integer",
                            "description": "Week number of the roster to get (optional)"
                        },
                        "day": {
                            "type": "string",
                            "description": "Day to get the roster (YYYY-MM-DD format, optional). If neither week nor day is specified, returns today's roster."
                        }
                    },
                    "required": ["team_key"]
                }
            ),
            Tool(
                name="get_team_details",
                description="Get detailed information about a specific team",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_key": {
                            "type": "string",
                            "description": "The team key to query"
                        }
                    },
                    "required": ["team_key"]
                }
            ),
            Tool(
                name="get_team_matchup",
                description="Get the opponent team key for a team's matchup in a given week",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_key": {
                            "type": "string",
                            "description": "The team key to query"
                        },
                        "week": {
                            "type": "integer",
                            "description": "Week number to find the matchup for"
                        }
                    },
                    "required": ["team_key", "week"]
                }
            ),
            Tool(
                name="get_team_proposed_trades",
                description="Get proposed trades that include the team (both offered and received)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_key": {
                            "type": "string",
                            "description": "The team key to query"
                        }
                    },
                    "required": ["team_key"]
                }
            ),
            Tool(
                name="get_matchup_scores",
                description="Get scores for current or specific matchup",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_key": {
                            "type": "string",
                            "description": "The team key to query"
                        },
                        "week": {
                            "type": "integer",
                            "description": "Week number (optional)"
                        }
                    },
                    "required": ["team_key"]
                }
            ),
            Tool(
                name="get_player_stats",
                description="Get statistics for one or more players for a specified time period",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        },
                        "player_ids": {
                            "type": "string",
                            "description": "Comma-separated list of Yahoo! player IDs"
                        },
                        "req_type": {
                            "type": "string",
                            "description": "Stats time range: 'season', 'average_season', 'lastweek', 'lastmonth', 'date', 'week'"
                        },
                        "date": {
                            "type": "string",
                            "description": "Date for stats (YYYY-MM-DD format, used with req_type='date')"
                        },
                        "week": {
                            "type": "integer",
                            "description": "Week number (used with req_type='week')"
                        },
                        "season": {
                            "type": "integer",
                            "description": "Season year (used with req_type='season')"
                        }
                    },
                    "required": ["league_id", "player_ids", "req_type"]
                }
            ),
            Tool(
                name="search_players",
                description="Search for players by name or get player details by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to search in"
                        },
                        "player": {
                            "description": "Player search: string for name search (returns up to 25 matches), integer for single player ID, or comma-separated integers for multiple player IDs"
                        }
                    },
                    "required": ["league_id", "player"]
                }
            ),
            Tool(
                name="get_free_agents",
                description="Get available free agents in a league for a specific position",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        },
                        "position": {
                            "type": "string",
                            "description": "Position filter (required). Use position codes like 'QB', 'RB', 'WR', 'TE', etc."
                        }
                    },
                    "required": ["league_id", "position"]
                }
            ),
            Tool(
                name="get_waivers",
                description="Get players currently on waivers in the league",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "league_id": {
                            "type": "string",
                            "description": "The league ID to query"
                        }
                    },
                    "required": ["league_id"]
                }
            ),
        ]
        read_tools = [
            tool.model_copy(update={"annotations": _READ_ONLY_ANNOTATIONS})
            for tool in read_tools
        ]
        return ListToolsResult(tools=read_tools + _WRITE_TOOLS)

    async def call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        """Handle tool calls.

        Args:
            ctx: Request context
            params: Tool call parameters (tool name and arguments)

        Returns:
            Tool result with text content
        """
        name = params.name
        arguments = params.arguments or {}
        try:
            if name == "get_team_key":
                result = await tools.get_team_key(arguments["league_id"])
            elif name == "get_current_week":
                result = await tools.get_current_week(arguments["league_id"])
            elif name == "get_edit_date":
                result = await tools.get_edit_date(arguments["league_id"])
            elif name == "get_end_week":
                result = await tools.get_end_week(arguments["league_id"])
            elif name == "get_matchups":
                result = await tools.get_matchups(
                    arguments["league_id"],
                    arguments.get("week")
                )
            elif name == "get_positions":
                result = await tools.get_positions(arguments["league_id"])
            elif name == "get_settings":
                result = await tools.get_settings(arguments["league_id"])
            elif name == "get_stat_categories":
                result = await tools.get_stat_categories(arguments["league_id"])
            elif name == "get_teams":
                result = await tools.get_teams(arguments["league_id"])
            elif name == "get_transactions":
                result = await tools.get_transactions(
                    arguments["league_id"],
                    arguments["tran_types"],
                    arguments.get("count")
                )
            elif name == "get_league_standings":
                result = await tools.get_league_standings(arguments["league_id"])
            elif name == "get_team_roster":
                result = await tools.get_team_roster(
                    arguments["team_key"],
                    arguments.get("week"),
                    arguments.get("day")
                )
            elif name == "get_team_details":
                result = await tools.get_team_details(arguments["team_key"])
            elif name == "get_team_matchup":
                result = await tools.get_team_matchup(
                    arguments["team_key"],
                    arguments["week"]
                )
            elif name == "get_team_proposed_trades":
                result = await tools.get_team_proposed_trades(arguments["team_key"])
            elif name == "get_matchup_scores":
                result = await tools.get_matchup_scores(
                    arguments["team_key"],
                    arguments.get("week")
                )
            elif name == "get_player_stats":
                # Parse comma-separated player IDs into list of integers.
                player_ids_str = arguments["player_ids"]
                player_ids = [int(x.strip()) for x in player_ids_str.split(',')]
                result = await tools.get_player_stats(
                    arguments["league_id"],
                    player_ids,
                    arguments["req_type"],
                    arguments.get("date"),
                    arguments.get("week"),
                    arguments.get("season")
                )
            elif name == "search_players":
                # Handle player input: can be string (name), int (single ID), or comma-separated ints.
                player_input = arguments["player"]
                if isinstance(player_input, str):
                    # Check if it's a comma-separated list of integers.
                    if ',' in player_input:
                        try:
                            player = [int(x.strip()) for x in player_input.split(',')]
                        except ValueError:
                            # Not all integers, treat as name search.
                            player = player_input
                    else:
                        # Try to parse as single integer.
                        try:
                            player = int(player_input)
                        except ValueError:
                            # Not an integer, treat as name search.
                            player = player_input
                else:
                    player = player_input
                result = await tools.search_players(arguments["league_id"], player)
            elif name == "get_free_agents":
                result = await tools.get_free_agents(
                    arguments["league_id"],
                    arguments["position"]
                )
            elif name == "get_waivers":
                result = await tools.get_waivers(arguments["league_id"])
            elif name == "change_positions":
                result = await tools.change_positions(
                    arguments["team_key"],
                    arguments["players"],
                    arguments.get("date"),
                    arguments.get("week")
                )
            elif name == "add_player":
                result = await tools.add_player(
                    arguments["team_key"],
                    int(arguments["player_id"])
                )
            elif name == "drop_player":
                result = await tools.drop_player(
                    arguments["team_key"],
                    int(arguments["player_id"])
                )
            elif name == "add_and_drop_players":
                result = await tools.add_and_drop_players(
                    arguments["team_key"],
                    int(arguments["add_player_id"]),
                    int(arguments["drop_player_id"])
                )
            elif name == "claim_player":
                result = await tools.claim_player(
                    arguments["team_key"],
                    int(arguments["player_id"]),
                    arguments.get("faab")
                )
            elif name == "claim_and_drop_players":
                result = await tools.claim_and_drop_players(
                    arguments["team_key"],
                    int(arguments["add_player_id"]),
                    int(arguments["drop_player_id"]),
                    arguments.get("faab")
                )
            elif name == "propose_trade":
                result = await tools.propose_trade(
                    arguments["team_key"],
                    arguments["tradee_team_key"],
                    [int(p) for p in arguments["your_player_ids"]],
                    [int(p) for p in arguments["their_player_ids"]],
                    arguments.get("trade_note", "")
                )
            elif name == "accept_trade":
                result = await tools.accept_trade(
                    arguments["team_key"],
                    arguments["transaction_key"],
                    arguments.get("trade_note", "")
                )
            elif name == "reject_trade":
                result = await tools.reject_trade(
                    arguments["team_key"],
                    arguments["transaction_key"],
                    arguments.get("trade_note", "")
                )
            else:
                raise ValueError(f"Unknown tool: {name}")

            return CallToolResult(content=[TextContent(type="text", text=str(result))])

        except Exception as e:
            logger.error(f"Error calling tool {name}: {e}")
            return CallToolResult(content=[TextContent(type="text", text=f"Error: {str(e)}")])

    return Server(
        "yahoo-fantasy",
        version=__version__,
        on_list_resources=list_resources,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )

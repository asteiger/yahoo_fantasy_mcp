"""Unit tests for the write tools, with the Yahoo! API mocked out."""

import datetime
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolRequestParams
from yahoo_fantasy_api.team import Team

from yahoo_fantasy_mcp import server
from yahoo_fantasy_mcp import tools as tools_module
from yahoo_fantasy_mcp.tools import YahooFantasyTools

TEAM_KEY = "423.l.123456.t.4"
OTHER_TEAM_KEY = "423.l.123456.t.7"

WRITE_TOOL_NAMES = {
    "change_positions",
    "add_player",
    "drop_player",
    "add_and_drop_players",
    "claim_player",
    "claim_and_drop_players",
    "propose_trade",
    "accept_trade",
    "reject_trade",
}


@pytest.fixture
def team(monkeypatch):
    """Replace yfa.Team with a mock and return the mock team instance."""
    team_instance = MagicMock()
    team_cls = MagicMock(return_value=team_instance)
    monkeypatch.setattr(tools_module.yfa, "Team", team_cls)
    return team_instance


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(tools_module, "OAuth2", MagicMock())
    return YahooFantasyTools(oauth2_file="oauth2.json")


async def test_change_positions_by_date(tools, team):
    players = [{"player_id": 5981, "selected_position": "BN"}]
    result = await tools.change_positions(TEAM_KEY, players, date="2026-09-14")

    assert result["success"] is True
    team.change_positions.assert_called_once_with(datetime.date(2026, 9, 14), players)


async def test_change_positions_by_week(tools, team):
    players = [{"player_id": 5981, "selected_position": "QB"}]
    result = await tools.change_positions(TEAM_KEY, players, week=3)

    assert result["success"] is True
    team.change_positions.assert_called_once_with(3, players)


@pytest.mark.parametrize("kwargs", [{}, {"date": "2026-09-14", "week": 3}])
async def test_change_positions_requires_one_time_frame(tools, team, kwargs):
    result = await tools.change_positions(TEAM_KEY, [], **kwargs)

    assert result["success"] is False
    assert "exactly one" in result["error"]
    team.change_positions.assert_not_called()


@pytest.mark.parametrize(
    "method, args, library_call",
    [
        ("add_player", (6767,), ("add_player", (6767,), {})),
        ("drop_player", (6770,), ("drop_player", (6770,), {})),
        ("add_and_drop_players", (6767, 6770), ("add_and_drop_players", (6767, 6770), {})),
        ("claim_player", (6767, 7), ("claim_player", (6767,), {"faab": 7})),
        (
            "claim_and_drop_players",
            (6767, 6770, 22),
            ("claim_and_drop_players", (6767, 6770), {"faab": 22}),
        ),
        ("accept_trade", ("423.l.123456.pt.1", "ok"), ("accept_trade", ("423.l.123456.pt.1", "ok"), {})),
        ("reject_trade", ("423.l.123456.pt.1",), ("reject_trade", ("423.l.123456.pt.1", ""), {})),
    ],
)
async def test_write_tools_call_library(tools, team, method, args, library_call):
    result = await getattr(tools, method)(TEAM_KEY, *args)

    assert result["success"] is True
    assert result["team_key"] == TEAM_KEY
    lib_method, lib_args, lib_kwargs = library_call
    getattr(team, lib_method).assert_called_once_with(*lib_args, **lib_kwargs)


async def test_write_failure_reports_yahoo_error(tools, team):
    team.drop_player.side_effect = RuntimeError(b"<error><description>Nope</description></error>")

    result = await tools.drop_player(TEAM_KEY, 6770)

    assert result["success"] is False
    assert result["error"] == "<error><description>Nope</description></error>"


async def test_propose_trade_posts_correct_players(tools, monkeypatch):
    yhandler = MagicMock()

    def make_team(sc, team_key):
        team = Team(sc, team_key)
        team.inject_yhandler(yhandler)
        return team

    monkeypatch.setattr(tools_module.yfa, "Team", make_team)

    result = await tools.propose_trade(TEAM_KEY, OTHER_TEAM_KEY, [101, 102], [201], "hi")

    assert result["success"] is True
    yhandler.post_transactions.assert_called_once()
    league_id, xml = yhandler.post_transactions.call_args.args
    assert league_id == "423.l.123456"
    assert "<trade_note>hi</trade_note>" in xml
    for player_key, source, destination in [
        ("423.p.101", TEAM_KEY, OTHER_TEAM_KEY),
        ("423.p.102", TEAM_KEY, OTHER_TEAM_KEY),
        ("423.p.201", OTHER_TEAM_KEY, TEAM_KEY),
    ]:
        player_xml = xml.split(f"<player_key>{player_key}</player_key>")[1].split("</player>")[0]
        assert f"<source_team_key>{source}</source_team_key>" in player_xml
        assert f"<destination_team_key>{destination}</destination_team_key>" in player_xml


@pytest.fixture
def mcp_server(monkeypatch):
    fake_tools = MagicMock()
    monkeypatch.setattr(server, "YahooFantasyTools", MagicMock(return_value=fake_tools))
    return server.create_server(oauth2_file="oauth2.json"), fake_tools


async def test_list_tools_annotates_reads_and_writes(mcp_server):
    srv, _ = mcp_server
    result = await srv._request_handlers["tools/list"].handler(None, None)
    by_name = {tool.name: tool for tool in result.tools}

    assert WRITE_TOOL_NAMES <= by_name.keys()
    for name, tool in by_name.items():
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is (name not in WRITE_TOOL_NAMES)
    assert by_name["drop_player"].annotations.destructive_hint is True
    assert by_name["add_player"].annotations.destructive_hint is False


async def test_call_tool_dispatches_write(mcp_server):
    srv, fake_tools = mcp_server
    fake_tools.propose_trade = MagicMock(return_value=_async_value({"success": True}))

    params = CallToolRequestParams(
        name="propose_trade",
        arguments={
            "team_key": TEAM_KEY,
            "tradee_team_key": OTHER_TEAM_KEY,
            "your_player_ids": [101],
            "their_player_ids": ["201"],
        },
    )
    result = await srv._request_handlers["tools/call"].handler(None, params)

    fake_tools.propose_trade.assert_called_once_with(TEAM_KEY, OTHER_TEAM_KEY, [101], [201], "")
    assert result.content[0].text == "{'success': True}"


async def _async_value(value):
    return value

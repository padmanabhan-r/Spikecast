import pytest

from spikecast import cli


def test_every_command_parses():
    parser = cli.build_parser()
    assert parser.parse_args(["serve", "--no-open"]).no_open
    assert parser.parse_args(["live", "--port", "9000"]).port == 9000
    record = parser.parse_args(["record", "dev", "--dt", "0.5", "--no-plasticity"])
    assert (record.scenario, record.dt, record.no_plasticity) == ("dev", 0.5, True)
    assert parser.parse_args(["narrate", "dev", "--no-voice"]).no_voice
    assert parser.parse_args(["broadcast", "dev"]).seed == 0


def test_unknown_scenario_names_the_known_ones():
    with pytest.raises(SystemExit) as error:
        cli._scenario_path("no-such-scenario")
    assert "dev" in str(error.value)


def test_serve_reuses_a_running_server(monkeypatch, capsys):
    """A second start must not fight the first for the port."""
    monkeypatch.setattr(cli, "_is_spikecast", lambda port: True)
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    assert cli.serve("/", 8000, open_browser=True) == 0
    assert opened == ["http://localhost:8000/"]
    assert "already running" in capsys.readouterr().out

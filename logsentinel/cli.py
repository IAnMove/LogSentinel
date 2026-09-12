"""Command Line Interface for LogSentinel."""

from __future__ import annotations
import asyncio
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer
import yaml
from logsentinel import __version__
from logsentinel.config import Config, get_default_config_dir, get_default_data_dir
from logsentinel.core.engine import SentinelEngine
from logsentinel.core.models import (
    Alert,
    AlertStatus,
    Category,
    Incident,
    LogEntry,
    MemoryRule,
    MemoryRuleType,
    Severity,
)
from logsentinel.collectors.file_reader import FileReader
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.memory.feedback import FeedbackLearner
from logsentinel.memory.matcher import MemoryMatcher
from logsentinel.memory.store import MemoryStore
from logsentinel.simulator.scenarios import SCENARIOS

app = typer.Typer(
    name="logsentinel",
    help="🛡️ LogSentinel: Intelligent Linux log monitoring and security sentinel with local LLM & adaptive memory.",
    no_args_is_help=True,
)
memory_app = typer.Typer(help="Manage adaptive memory and ignore rules.")
alerts_app = typer.Typer(help="Inspect and manage generated security alerts.")
config_app = typer.Typer(help="View and manage configuration settings.")
service_app = typer.Typer(help="Manage systemd background service.")

app.add_typer(memory_app, name="memory")
app.add_typer(alerts_app, name="alerts")
app.add_typer(config_app, name="config")
app.add_typer(service_app, name="service")

console = Console()


def print_alert_card(alert: Alert) -> None:
    """Render a formatted Rich card for an alert."""
    sev = alert.verdict.severity
    color_map = {
        Severity.CRITICAL: "bold red",
        Severity.HIGH: "red",
        Severity.MEDIUM: "yellow",
        Severity.LOW: "blue",
        Severity.INFO: "green",
    }
    color = color_map.get(sev, "white")

    content = Text()
    content.append(f"Summary: {alert.verdict.summary}\n", style="bold")
    content.append(f"Service: {alert.incident.service}  |  Events: {alert.incident.count}  |  Category: {alert.verdict.category.value}\n")
    if alert.verdict.recommended_action:
        content.append(f"Action:  {alert.verdict.recommended_action}\n", style="cyan")
    if alert.channels_notified:
        content.append(f"Notified via: {', '.join(alert.channels_notified)}\n", style="dim")
    content.append(f"Alert ID: {alert.id}  (Dismiss: logsentinel alerts dismiss {alert.id} --always)", style="dim italic")

    panel = Panel(
        content,
        title=f"[{color}]🛡️ [{sev.value}] {alert.verdict.title}[/]",
        border_style=color,
        subtitle=f"[dim]{alert.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}[/dim]",
    )
    console.print(panel)


@app.command()
def run(
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Legacy monitor. Prefer `logsentinel portal` for the current product."""
    console.print(
        "[yellow]The 'run' command is the legacy engine with a separate database. "
        "Use `logsentinel portal` for the current observatory.[/yellow]"
    )
    cfg = Config.load(config_file)
    console.print(Panel.fit(
        f"[bold cyan]LogSentinel v{__version__}[/bold cyan] [green]ONLINE[/green]\n"
        f"[dim]LLM Provider:[/dim] [yellow]{cfg.llm.provider}[/yellow] ([white]{cfg.llm.model}[/white]) @ {cfg.llm.base_url}\n"
        f"[dim]Sources:[/dim] journald={cfg.sources.journald.enabled}, files={len(cfg.sources.files.paths)}\n"
        f"[dim]Memory DB:[/dim] {cfg.app.get_resolved_db_path()}\n"
        f"[dim]Press Ctrl+C to stop.[/dim]",
        title="🛡️ LogSentinel Daemon",
        border_style="cyan",
    ))

    async def _alert_callback(alert: Alert) -> None:
        print_alert_card(alert)

    engine = SentinelEngine(cfg, on_alert_callback=_alert_callback)

    async def _main():
        await engine.start()
        try:
            while True:
                await asyncio.sleep(1.0)
                engine.raise_if_failed()
        except asyncio.CancelledError:
            pass
        finally:
            console.print("\n[yellow]Shutting down LogSentinel...[/yellow]")
            await engine.stop()
            console.print("[green]Shutdown complete.[/green]")

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


async def _evaluate_batch(engine, entries, show_logs=False):
    """Capture every callback result, including threshold-triggered flushes."""
    alerts = []
    count = 0
    original_callback = engine.aggregator.on_incident_ready

    async def evaluate(incident):
        nonlocal count
        count += 1
        alert = await engine.process_incident(incident)
        if alert:
            alerts.append(alert)

    engine.aggregator.on_incident_ready = evaluate
    try:
        for entry in entries:
            if show_logs:
                console.print(f"  Log: {entry.message}", markup=False)
            await engine.ingest_log(entry)
        await engine.aggregator.flush_all()
    finally:
        engine.aggregator.on_incident_ready = original_callback
    return count, alerts


@app.command()
def scan(
    target: str = typer.Argument(..., help="File path or 'journald' to scan"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to read"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Scan historical logs in batch and evaluate security/errors."""
    cfg = Config.load(config_file)
    engine = SentinelEngine(cfg)

    console.print(f"[cyan]Scanning {target} (up to {lines} lines)...[/cyan]")

    entries = []
    if target.lower() == "journald":
        j_col = JournaldCollector(cfg.sources.journald)
        entries = asyncio.run(j_col.read_recent(lines=lines))
    else:
        entries = FileReader.read_file(target, max_lines=lines)

    console.print(f"[dim]Read {len(entries)} entries. Running through prefilter & analysis...[/dim]")

    async def _analyze():
        count, results = await _evaluate_batch(engine, entries)
        console.print(f"[cyan]Evaluated {count} candidate incidents.[/cyan]")
        alerts = [a for a in results if a.status != AlertStatus.AUTO_SUPPRESSED]
        for alert in alerts:
            print_alert_card(alert)
        if not alerts:
            console.print("[green]✓ No critical security alerts or errors identified.[/green]")

    asyncio.run(_analyze())


@app.command()
def simulate(
    scenario: str = typer.Argument(
        ...,
        help=f"Scenario to simulate: {', '.join(SCENARIOS.keys())}",
    ),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Simulate realistic security attacks or system failures to test the system."""
    if scenario not in SCENARIOS:
        console.print(f"[red]Error: Unknown scenario '{scenario}'. Available: {list(SCENARIOS.keys())}[/red]")
        raise typer.Exit(1)

    cfg = Config.load(config_file)
    engine = SentinelEngine(cfg)

    generator = SCENARIOS[scenario]
    entries = generator()

    console.print(Panel(
        f"Simulating [bold cyan]{scenario}[/bold cyan] with {len(entries)} synthetic log lines...",
        title="🧪 Simulation Test",
        border_style="yellow",
    ))

    async def _run_sim():
        count, alerts = await _evaluate_batch(engine, entries, show_logs=True)
        console.print(f"\n[cyan]Evaluated {count} incident(s) with memory & LLM.[/cyan]")
        for alert in alerts:
            if alert:
                if alert.status == AlertStatus.AUTO_SUPPRESSED:
                    console.print(Panel(
                        f"[yellow]Suppressed by Memory / Rule:[/yellow] {alert.suppression_reason}\n"
                        f"[dim]Incident:[/dim] {alert.incident.service} - {alert.incident.signature}",
                        title="🛡️ [dim]Suppressed (No notification)[/dim]",
                        border_style="yellow",
                    ))
                else:
                    print_alert_card(alert)

    asyncio.run(_run_sim())


@app.command(name="ignore")
def ignore_quick(
    instruction_or_pattern: str = typer.Argument(..., help="Pattern, service, IP, or natural language to ignore"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Quick command to teach LogSentinel to ignore an event or pattern."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    learner = FeedbackLearner(store)

    rule = learner.learn_from_text(instruction_or_pattern)
    console.print(f"[green]✓ Memory rule learned & stored successfully![/green]")
    console.print(f"  [bold]ID:[/bold] {rule.id}")
    console.print(f"  [bold]Type:[/bold] {rule.rule_type.value}")
    console.print(f"  [bold]Rule:[/bold] {rule.content}")


@app.command()
def test(
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Run self-test diagnostics on LLM, logs, database, and notifications."""
    cfg = Config.load(config_file)
    console.print(Panel("[bold]Running LogSentinel Diagnostics...[/bold]", border_style="cyan"))
    failed = False

    # 1. Systemd / Journalctl
    j_col = JournaldCollector(cfg.sources.journald)
    if j_col.is_available():
        console.print("[green]✓ Systemd journalctl:[/green] Binary available (journal permissions not tested).")
    else:
        console.print("[yellow]⚠ Systemd journalctl:[/yellow] Not found (file log sources will be used).")

    # 2. Database
    try:
        store = MemoryStore(cfg.app.get_resolved_db_path())
        rule_count = len(store.list_rules())
        alert_count = len(store.list_alerts())
        console.print(f"[green]✓ SQLite Memory Store:[/green] Healthy ({rule_count} active rules, {alert_count} alerts logged).")
    except Exception as e:
        failed = True
        console.print(f"[red]✗ SQLite Database Error:[/red] {e}")

    # 3. LLM Connectivity
    console.print(f"[cyan]Testing connection to LLM ({cfg.llm.provider} @ {cfg.llm.base_url})...[/cyan]")
    engine = SentinelEngine(cfg)
    health = asyncio.run(engine.llm_client.check_health())
    if health.get("status") == "healthy":
        console.print(f"[green]✓ LLM Service Connected:[/green] Provider={health.get('provider')}, Configured Model={health.get('configured_model')}")
        avail = health.get("available_models", [])
        console.print(f"  [dim]Available models on server: {', '.join(avail) if avail else 'None listed'}[/dim]")
    else:
        failed = True
        console.print(f"[red]✗ LLM Connection Failed:[/red] {health.get('error')}")

    # 4. Notifications
    console.print("[cyan]Testing notification channels...[/cyan]")
    notif_results = asyncio.run(engine.dispatcher.test_all())
    for channel, ok in notif_results.items():
        if ok:
            console.print(f"[green]✓ Notifier ({channel}):[/green] Sent test notification successfully.")
        else:
            failed = True
            console.print(f"[yellow]⚠ Notifier ({channel}):[/yellow] Skipped or failed test.")

    if failed:
        raise typer.Exit(1)


# --- Memory Subcommands ---

@memory_app.command(name="list")
def memory_list(
    active_only: bool = typer.Option(True, "--active-only/--all", help="List all or only active rules"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """List all stored memory and ignore rules."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    rules = store.list_rules(active_only=active_only)

    if not rules:
        console.print("[yellow]No memory rules found. Add one with `logsentinel ignore <pattern>`[/yellow]")
        return

    table = Table(title="🧠 LogSentinel Memory & Suppression Rules", header_style="bold cyan")
    table.add_column("Rule ID", style="bold", width=12)
    table.add_column("Type", style="magenta", width=12)
    table.add_column("Content / Instruction", style="white")
    table.add_column("Hits", justify="right", style="green", width=6)
    table.add_column("Created", style="dim", width=19)

    for r in rules:
        table.add_row(
            r.id,
            r.rule_type.value,
            r.content,
            str(r.hit_count),
            r.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@memory_app.command(name="add")
def memory_add(
    content: str = typer.Argument(..., help="Rule content or instruction"),
    rule_type: Optional[str] = typer.Option(None, "--type", "-t", help="PATTERN, SERVICE, IP_ADDRESS, or SEMANTIC"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="Optional description"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Add a new suppression or semantic memory rule."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    learner = FeedbackLearner(store)

    m_type = None
    if rule_type:
        try:
            m_type = MemoryRuleType(rule_type.upper())
        except ValueError:
            console.print(f"[red]Invalid rule type '{rule_type}'. Valid types: PATTERN, SERVICE, IP_ADDRESS, SEMANTIC[/red]")
            raise typer.Exit(1)

    rule = learner.learn_from_text(content, rule_type=m_type, description=description)
    console.print(f"[green]✓ Memory rule added:[/green] {rule.id} ({rule.rule_type.value}): {rule.content}")


@memory_app.command(name="remove")
def memory_remove(
    rule_id: str = typer.Argument(..., help="Rule ID to delete"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Delete a memory rule."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    success = store.delete_rule(rule_id)
    if success:
        console.print(f"[green]✓ Rule {rule_id} removed.[/green]")
    else:
        console.print(f"[red]Rule {rule_id} not found.[/red]")


@memory_app.command(name="clear")
def memory_clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Confirm clear all rules"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Clear all stored memory rules."""
    if not confirm:
        confirm = typer.confirm("Are you sure you want to delete ALL memory rules?")
    if confirm:
        cfg = Config.load(config_file)
        store = MemoryStore(cfg.app.get_resolved_db_path())
        count = store.clear_all_rules()
        console.print(f"[yellow]Cleared {count} memory rule(s).[/yellow]")


@memory_app.command(name="test")
def memory_test(
    log_line: str = typer.Argument(..., help="Log line to test against memory rules"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Check if a log line would be suppressed by existing memory rules."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    matcher = MemoryMatcher(store)

    entry = LogEntry(service="test", message=log_line, raw=log_line)
    incident = Incident(service="test", signature="test", entries=[entry])

    suppressed, rule = matcher.evaluate_fast_suppression(incident)
    if suppressed and rule:
        console.print(f"[yellow]✓ MATCH! Log line IS SUPPRESSED by rule {rule.id} ({rule.rule_type.value}):[/yellow]")
        console.print(f"  Content: {rule.content}")
    else:
        console.print("[green]✗ No fast suppression match. Log line would proceed to LLM analysis.[/green]")


# --- Alerts Subcommands ---

@alerts_app.command(name="list")
def alerts_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Max alerts to show"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """List recent alerts from the database."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    alerts = store.list_alerts(limit=limit)

    if not alerts:
        console.print("[green]No alerts recorded yet.[/green]")
        return

    table = Table(title="🚨 LogSentinel Alerts History", header_style="bold cyan")
    table.add_column("Alert ID", style="bold", width=14)
    table.add_column("Severity", width=10)
    table.add_column("Service", width=12)
    table.add_column("Title", style="white", width=28, no_wrap=False)
    table.add_column("Status", width=15)
    table.add_column("Timestamp", style="dim", width=19)

    for a in alerts:
        sev = a.verdict.severity.value
        status = a.status.value
        table.add_row(
            a.id,
            sev,
            a.incident.service,
            a.verdict.title,
            status,
            a.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@alerts_app.command(name="show")
def alerts_show(
    alert_id: str = typer.Argument(..., help="Alert ID to inspect"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Show complete details and raw logs of an alert."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    alert = store.get_alert(alert_id)
    if not alert:
        console.print(f"[red]Alert {alert_id} not found.[/red]")
        raise typer.Exit(1)

    print_alert_card(alert)
    console.print("\n[bold cyan]Raw Log Samples:[/bold cyan]")
    for e in alert.incident.entries[:10]:
        console.print(f"  • {e.message}")
    if alert.verdict.reasoning:
        console.print(f"\n[dim]LLM Reasoning: {alert.verdict.reasoning}[/dim]")


@alerts_app.command(name="dismiss")
def alerts_dismiss(
    alert_id: str = typer.Argument(..., help="Alert ID to dismiss"),
    always: bool = typer.Option(False, "--always", "-a", help="Create permanent memory rule to ignore similar events"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Optional reason for dismissal"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Dismiss an alert and optionally remember to ignore future occurrences."""
    cfg = Config.load(config_file)
    store = MemoryStore(cfg.app.get_resolved_db_path())
    learner = FeedbackLearner(store)

    alert = store.get_alert(alert_id)
    if not alert:
        console.print(f"[red]Alert {alert_id} not found.[/red]")
        raise typer.Exit(1)

    store.update_alert_status(alert_id, AlertStatus.DISMISSED, feedback=reason)
    console.print(f"[green]✓ Alert {alert_id} marked as DISMISSED.[/green]")

    if always:
        rule = learner.learn_from_alert_dismiss(alert, instruction=reason, create_permanent_rule=True)
        if rule:
            console.print(f"[cyan]🧠 Created permanent ignore rule:[/cyan] {rule.id} ({rule.content})")


# --- Config Subcommands ---

@config_app.command(name="show")
def config_show(
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
) -> None:
    """Print current configuration."""
    cfg = Config.load(config_file)
    data = cfg.model_dump()
    data["llm"]["api_key"] = "[REDACTED]" if data["llm"]["api_key"] else None
    for channel, fields in {
        "telegram": ("bot_token", "chat_id"),
        "discord": ("webhook_url",),
        "slack": ("webhook_url",),
        "generic_webhook": ("url", "headers"),
    }.items():
        for field in fields:
            if data["notifiers"][channel][field]:
                data["notifiers"][channel][field] = "[REDACTED]"
    console.print(yaml.dump(data, default_flow_style=False, sort_keys=False), markup=False)


@config_app.command(name="init")
def config_init(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Target config path"),
) -> None:
    """Initialize default configuration file."""
    cfg = Config()
    target_path = Path(path) if path else get_default_config_dir() / "config.yaml"
    if target_path.expanduser().exists():
        console.print("Configuration already exists; choose a new path.")
        raise typer.Exit(1)
    saved = cfg.save(target_path)
    console.print(f"[green]✓ Configuration saved to:[/green] {saved}")


# --- Service Subcommands ---

SYSTEM_UNIT_DIR = Path("/etc/systemd/system")

# Applied to every generated unit. A log reader needs no privilege beyond reading
# the files it was granted, so the unit drops capabilities and write access up front
# instead of relying on the operator to remember.
SERVICE_HARDENING = """NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
UMask=0077"""


@service_app.command(name="install")
def service_install(
    system: bool = typer.Option(False, "--system", help="Install system-wide service (/etc/systemd/system)"),
    run_as: Optional[str] = typer.Option(None, "--run-as", help="Account for a system service (default: current user)"),
    allow_root: bool = typer.Option(False, "--allow-root", help="Permit a system service running as root"),
    legacy: bool = typer.Option(False, "--legacy", help="Install the old CLI monitor instead of the portal"),
) -> None:
    """Generate and install a systemd user or system unit for the portal."""
    import getpass

    account = ""
    if system:
        # A system unit without User= runs as root. Reading logs never requires that,
        # so name the account explicitly and refuse root unless it is asked for.
        account = run_as or getpass.getuser()
        if account == "root" and not allow_root:
            console.print(
                "[red]A system service would run as root.[/red] Pass --run-as with a "
                "dedicated account that can read the logs, or --allow-root to accept it."
            )
            raise typer.Exit(1)
    elif run_as:
        raise typer.BadParameter("--run-as applies to --system units; a user unit runs as you")

    identity = "" if not account or account == "root" else f"User={account}\nGroup={account}\n"
    # The daemon resolves its data directory from the running account's home, so only
    # grant write access when this install knows that path: the account is ours.
    own_account = not account or account == getpass.getuser()
    data_root = get_default_data_dir() if legacy else Path.home() / ".local/share/logsentinel"
    writable = f"ReadWritePaths={data_root}\n" if own_account else ""
    if legacy:
        start = f"{sys.executable} -m logsentinel.cli run"
        description = "LogSentinel legacy log monitor"
    else:
        start = (
            f"{sys.executable} -m logsentinel.cli portal "
            f"--data-dir {Path(data_root) / 'portal'} --port 8765"
        )
        description = "LogSentinel local log review portal"
    unit_content = f"""[Unit]
Description={description}
After=network.target

[Service]
Type=simple
{identity}ExecStart={start}
Restart=on-failure
RestartSec=5s
Environment=PYTHONUNBUFFERED=1
{writable}{SERVICE_HARDENING}

[Install]
WantedBy=default.target
"""
    if system:
        unit_dir = SYSTEM_UNIT_DIR
    else:
        unit_dir = Path.home() / ".config" / "systemd" / "user"

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / "logsentinel.service"

    with open(unit_file, "w") as f:
        f.write(unit_content)

    console.print(f"[green]✓ Systemd unit written to:[/green] {unit_file}")
    if account and not own_account:
        console.print(
            f"[yellow]Add ReadWritePaths for the data directory of {account}[/yellow] "
            "before starting; the unit grants no write access yet."
        )
    if not system:
        console.print("[cyan]To enable and start:[/cyan]")
        console.print("  systemctl --user daemon-reload")
        console.print("  systemctl --user enable --now logsentinel")
    else:
        console.print("[cyan]To enable and start:[/cyan]")
        console.print("  sudo systemctl daemon-reload")
        console.print("  sudo systemctl enable --now logsentinel")


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _split_listen(value: str) -> tuple[str, int]:
    """Split HOST:PORT, accepting a bracketed IPv6 literal."""
    host, _, port = value.rpartition(":")
    host = host.strip("[]")
    if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise typer.BadParameter("Use HOST:PORT, for example 0.0.0.0:8767")
    return host, int(port)


@app.command(name="portal")
def portal(data_dir: str = typer.Option("~/.local/share/logsentinel/portal", "--data-dir"),
           port: int = typer.Option(8765, "--port"),
           ingest_listen: Optional[str] = typer.Option(None, "--ingest-listen", help="HOST:PORT serving reception only, separate from the panel"),
           tls_cert: Optional[str] = typer.Option(None, "--tls-cert", help="Certificate for the reception listener"),
           tls_key: Optional[str] = typer.Option(None, "--tls-key", help="Private key for the reception listener")) -> None:
    """Run the local portal and its independent monitoring workers."""
    import uvicorn
    from logsentinel.portal.app import create_app
    if (tls_cert or tls_key) and not ingest_listen:
        raise typer.BadParameter("--tls-cert and --tls-key apply to --ingest-listen")
    if bool(tls_cert) != bool(tls_key):
        raise typer.BadParameter("Give both --tls-cert and --tls-key")
    ingest_host = ingest_port = None
    if ingest_listen:
        ingest_host, ingest_port = _split_listen(ingest_listen)
        # Loopback stays open for an SSH tunnel and for local testing. Anything
        # reachable from the network carries source tokens, so it needs TLS.
        if ingest_host not in LOOPBACK and not tls_cert:
            raise typer.BadParameter(
                "A reception listener outside loopback requires --tls-cert and --tls-key"
            )
        for label, path in (("certificate", tls_cert), ("private key", tls_key)):
            if path and not Path(path).expanduser().is_file():
                raise typer.BadParameter(f"Cannot read the TLS {label}: {path}")
    application = create_app(data_dir)
    console.print(f"Portal: http://127.0.0.1:{port}")
    # stdout is often captured by journald and then read back as log evidence.
    # Keep the bootstrap credential in an owner-only local file instead.
    key_path = application.state.store.write_access_key()
    console.print("Read the access key for local login from:", key_path, markup=False)
    if not ingest_listen:
        uvicorn.run(application, host="127.0.0.1", port=port, proxy_headers=False)
        return

    from logsentinel.portal.ingest import create_ingest_app

    scheme = "https" if tls_cert else "http"
    console.print(f"Reception: {scheme}://{ingest_host}:{ingest_port} (senders only)")
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                application, host="127.0.0.1", port=port, proxy_headers=False
            )
        ),
        uvicorn.Server(
            uvicorn.Config(
                create_ingest_app(
                    application.state.store, application.state.telemetry
                ),
                host=ingest_host,
                port=ingest_port,
                proxy_headers=False,
                ssl_certfile=tls_cert,
                ssl_keyfile=tls_key,
            )
        ),
    ]

    async def serve():
        await asyncio.gather(*(server.serve() for server in servers))

    asyncio.run(serve())


@app.command(name="forward")
def forward_command(path: str, receiver: str = typer.Option(..., "--receiver"),
                    source_id: str = typer.Option(..., "--source-id"),
                    spool: str = typer.Option(..., "--spool"),
                    token_env: str = typer.Option("LOGSENTINEL_PUSH_TOKEN", "--token-env"),
                    once: bool = typer.Option(False, "--once")) -> None:
    """Forward a file through HTTPS or an SSH tunnel, keeping unacknowledged events."""
    from logsentinel.portal.forward import forward
    token = os.environ.get(token_env)
    if not token:
        raise typer.BadParameter("Set the sender token in the selected environment variable")
    asyncio.run(forward(path, receiver, source_id, token, spool, once))


@app.command(name="metrics-forward")
def metrics_forward_command(
    receiver: str = typer.Option(..., "--receiver"),
    machine_id: str = typer.Option(..., "--machine-id"),
    interval: int = typer.Option(60, "--interval", min=10, max=3600),
    disk: list[str] = typer.Option(None, "--disk"),
    spool: str = typer.Option("~/.local/share/logsentinel/metrics-spool", "--spool"),
    once: bool = typer.Option(False, "--once"),
):
    """Send this Linux host's metrics with a durable queue. Token: LOGSENTINEL_METRICS_TOKEN."""
    import os
    from logsentinel.portal.telemetry_forward import forward_metrics
    token = os.environ.get("LOGSENTINEL_METRICS_TOKEN", "")
    if not token:
        raise typer.BadParameter("Set LOGSENTINEL_METRICS_TOKEN to the machine's metrics token")
    asyncio.run(forward_metrics(receiver, machine_id, token, spool, interval, disk, once))


@app.command(name="enrollment-package")
def enrollment_package(
    source_id: str = typer.Option(..., "--source-id", help="Push source this package enrolls"),
    receiver: str = typer.Option(..., "--receiver", help="Address the sender will reach, e.g. https://central.lan:8767"),
    data_dir: str = typer.Option("~/.local/share/logsentinel/portal", "--data-dir"),
    ca_cert: Optional[str] = typer.Option(None, "--ca-cert", help="PEM certificate the sender must trust"),
    validity: int = typer.Option(3600, "--validity", min=60, max=604800, help="Seconds the code stays valid"),
    out: str = typer.Option(..., "--out", help="Where to write the package"),
) -> None:
    """Write the onboarding package a sender imports. Run this on the central."""
    import json
    from logsentinel.portal.store import Store
    from logsentinel.portal.enroll import issue_package
    certificate = Path(ca_cert).expanduser().read_text() if ca_cert else ""
    try:
        package = issue_package(Store(data_dir), source_id, receiver, certificate, validity)
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal))
    target = Path(out).expanduser()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(package, handle, indent=2)
    console.print(f"[green]\u2713 Package written to:[/green] {target}")
    console.print("Deliver it over a channel you trust; it holds a single-use code, not the credential.")
    if package.get("fingerprint"):
        console.print("Certificate fingerprint:", package["fingerprint"], markup=False)


@app.command(name="enroll")
def enroll_command(
    package_file: str = typer.Argument(..., help="Package written by the central"),
    spool: str = typer.Option(..., "--spool", help="Directory holding this sender's queue and credential"),
) -> None:
    """Redeem an onboarding package and store this sender's credential."""
    import json
    from logsentinel.portal.enrollment_client import claim
    package = json.loads(Path(package_file).expanduser().read_text())
    try:
        result = claim(package, Path(spool).expanduser())
    except ValueError as refusal:
        console.print(f"[red]{refusal}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]\u2713 Enrolled as source[/green] {result['source_id']}")
    console.print("Credential stored in:", result["token_path"], markup=False)
    if result.get("ca_path"):
        console.print("Trusted certificate stored in:", result["ca_path"], markup=False)
    console.print("[cyan]Start forwarding with:[/cyan]")
    console.print(
        f"  LOGSENTINEL_PUSH_TOKEN=$(cat {result['token_path']}) logsentinel forward /path/app.log "
        f"--receiver {result['receiver']} --source-id {result['source_id']} --spool {spool}"
    )


@app.command(name="prepare-host")
def prepare_host(
    account: str = typer.Option("logsentinel-agent", "--account", help="System account the agent will run as"),
    source: list[str] = typer.Option(None, "--source", help="Log file or directory to grant read access to"),
    journal: bool = typer.Option(False, "--journal", help="Also grant read access to the whole systemd journal"),
    apply_changes: bool = typer.Option(False, "--apply", help="Make the changes; without it nothing is touched"),
) -> None:
    """Create the agent's account and grant it read access. Shows the plan before acting."""
    from logsentinel import hostprep
    try:
        targets = [hostprep.check_source(item) for item in (source or [])]
    except ValueError as refusal:
        raise typer.BadParameter(str(refusal))
    if not targets and not journal:
        raise typer.BadParameter("Name at least one --source or pass --journal")
    steps = hostprep.plan(account, targets, journal)

    table = Table(title="Planned changes", show_lines=False)
    table.add_column("Command", style="cyan", overflow="fold")
    table.add_column("Why", overflow="fold")
    for step in steps:
        table.add_row(" ".join(step["command"]), step["why"])
    console.print(table)
    for note in hostprep.rotation_notes(targets, account):
        console.print(f"[yellow]Note:[/yellow] {note}")
    if not apply_changes:
        console.print("[yellow]Nothing was changed.[/yellow] Re-run with --apply as root to make it so.")
        return
    try:
        hostprep.apply(steps)
    except PermissionError as refusal:
        console.print(f"[red]{refusal}[/red]")
        raise typer.Exit(1)
    except RuntimeError as failure:
        console.print(f"[red]Stopped: {failure}[/red]")
        raise typer.Exit(1)

    console.print("[green]\u2713 Applied.[/green] Reading back as the account itself:")
    unreadable = []
    for check in hostprep.verify(account, targets, journal):
        mark = "[green]readable[/green]" if check["readable"] else "[red]NOT readable[/red]"
        console.print(f"  {check['target']}: {mark}")
        if not check["readable"]:
            unreadable.append(check["target"])
    if unreadable:
        console.print(
            "[red]Some sources are still unreachable.[/red] Check the directories above them "
            "and whether the owning program restricts its files further."
        )
        raise typer.Exit(1)
    console.print(f"[cyan]Install the service with:[/cyan] logsentinel service install --system --run-as {account}")


@app.command(name="spool-status")
def spool_status(spool: str = typer.Option(..., "--spool")) -> None:
    """Read sender queue counts and errors without opening or changing the spool."""
    import json
    import sqlite3
    path = Path(spool).expanduser().resolve() / "sentinel.db"
    if not path.is_file():
        raise typer.BadParameter("Spool database does not exist")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        counts = dict(db.execute("SELECT status,count(*) FROM events GROUP BY status"))
        oldest = db.execute("SELECT min(received) FROM events WHERE status='pending'").fetchone()[0]
        workers = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM meta WHERE key IN ('sender_capture','sender_delivery','sender_quarantine')")}
    print(json.dumps(dict(counts=counts, oldest_pending=oldest, workers=workers), indent=2))


@app.command(name="restore")
def restore_backup(backup: str, data_dir: str = typer.Option(..., "--data-dir")) -> None:
    """Restore a portal backup into a NEW directory (never overwrite live data)."""
    import sqlite3
    import shutil
    target = Path(data_dir).expanduser().resolve()
    if target.exists():
        raise typer.BadParameter("Restore target must not exist")
    source = Path(backup).expanduser().resolve()
    with sqlite3.connect(source.as_uri()+"?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise typer.BadParameter("Backup integrity check failed")
        if conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != '1':
            raise typer.BadParameter("Unsupported backup schema")
    target.mkdir(mode=0o700, parents=True)
    shutil.copyfile(source, target / "sentinel.db")
    os.chmod(target / "sentinel.db", 0o600)
    from logsentinel.portal.store import Store

    restored = Store(target)
    restored.write_access_key()
    console.print(
        f"Restored to {target}. The backup includes secrets and the previous "
        "access key; rotate the access key, sender tokens and notification "
        "credentials before using this copy.",
        markup=False,
    )


def main() -> None:
    """CLI entrypoint."""
    app()


if __name__ == "__main__":
    main()

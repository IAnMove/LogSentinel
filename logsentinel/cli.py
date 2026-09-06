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
from logsentinel.config import Config, get_default_config_dir
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
    """Start real-time monitoring of Linux logs."""
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

@service_app.command(name="install")
def service_install(
    system: bool = typer.Option(False, "--system", help="Install system-wide service (/etc/systemd/system)"),
) -> None:
    """Generate and install systemd service unit."""
    unit_content = f"""[Unit]
Description=LogSentinel AI Log Monitoring Daemon
After=network.target

[Service]
Type=simple
ExecStart={sys.executable} -m logsentinel.cli run
Restart=always
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    if system:
        unit_dir = Path("/etc/systemd/system")
    else:
        unit_dir = Path.home() / ".config" / "systemd" / "user"

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file = unit_dir / "logsentinel.service"

    with open(unit_file, "w") as f:
        f.write(unit_content)

    console.print(f"[green]✓ Systemd unit written to:[/green] {unit_file}")
    if not system:
        console.print("[cyan]To enable and start:[/cyan]")
        console.print("  systemctl --user daemon-reload")
        console.print("  systemctl --user enable --now logsentinel")
    else:
        console.print("[cyan]To enable and start:[/cyan]")
        console.print("  sudo systemctl daemon-reload")
        console.print("  sudo systemctl enable --now logsentinel")


@app.command(name="portal")
def portal(data_dir: str = typer.Option("~/.local/share/logsentinel/portal", "--data-dir"),
           port: int = typer.Option(8765, "--port")) -> None:
    """Run the local portal and its independent monitoring workers."""
    import uvicorn
    from logsentinel.portal.app import create_app
    application = create_app(data_dir)
    console.print(f"Portal: http://127.0.0.1:{port}")
    console.print("Access key (enter in the local login form):", markup=False)
    console.print(application.state.store.meta("admin_token"), markup=False)
    uvicorn.run(application, host="127.0.0.1", port=port, proxy_headers=False)


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


@app.command(name="restore")
def restore_backup(backup: str, data_dir: str = typer.Option(..., "--data-dir")) -> None:
    """Restore a portal backup into a NEW directory (never overwrite live data)."""
    import sqlite3
    import shutil
    target = Path(data_dir).expanduser().resolve()
    if target.exists():
        raise typer.BadParameter("Restore target must not exist")
    source = Path(backup).expanduser().resolve()
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise typer.BadParameter("Backup integrity check failed")
        if conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] != '1':
            raise typer.BadParameter("Unsupported backup schema")
    target.mkdir(mode=0o700, parents=True)
    shutil.copyfile(source, target / "sentinel.db")
    os.chmod(target / "sentinel.db", 0o600)
    console.print(f"Restored to {target}. The backup includes secrets; rotate sender/admin tokens if needed.", markup=False)


def main() -> None:
    """CLI entrypoint."""
    app()


if __name__ == "__main__":
    main()

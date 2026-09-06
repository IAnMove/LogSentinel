"""Core Sentinel engine coordinating ingestion, filtering, memory, LLM, and alerts."""

from __future__ import annotations
import asyncio
from typing import Callable, Coroutine, List, Optional
from logsentinel.config import Config
from logsentinel.core.aggregator import LogAggregator
from logsentinel.core.models import (
    Alert,
    AlertStatus,
    Category,
    Incident,
    LLMVerdict,
    LogEntry,
    Severity,
)
from logsentinel.core.prefilter import PreFilter
from logsentinel.collectors.file_tailer import FileTailerCollector
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.llm.client import LLMClient
from logsentinel.memory.behavior import BehaviorProfiler
from logsentinel.memory.feedback import FeedbackLearner
from logsentinel.memory.matcher import MemoryMatcher
from logsentinel.memory.store import MemoryStore
from logsentinel.notifiers.dispatcher import NotificationDispatcher


class SentinelEngine:
    """The main orchestration engine for LogSentinel."""

    def __init__(
        self,
        config: Config,
        on_alert_callback: Optional[Callable[[Alert], Coroutine[None, None, None]]] = None,
    ):
        self.config = config
        self.on_alert_callback = on_alert_callback

        # Initialize components
        self.prefilter = PreFilter(config.prefilter)
        self.memory_store = MemoryStore(config.app.get_resolved_db_path())
        self.behavior = BehaviorProfiler(self.memory_store.db_path, config.behavior)
        self.memory_matcher = MemoryMatcher(self.memory_store)
        self.feedback_learner = FeedbackLearner(self.memory_store)
        self.llm_client = LLMClient(config.llm)
        self.dispatcher = NotificationDispatcher(
            config.notifiers,
            default_file_path=config.app.get_resolved_alerts_path(),
        )

        self.aggregator = LogAggregator(
            config.aggregator,
            on_incident_ready=self.process_incident,
        )

        self.journald_collector = JournaldCollector(config.sources.journald)
        self.file_collector = FileTailerCollector(config.sources.files)

        self._running = False
        self._collector_tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        """Start real-time monitoring and processing pipelines."""
        self._running = True
        await self.aggregator.start()

        # Start journald collector task if enabled
        if self.config.sources.journald.enabled and self.journald_collector.is_available():
            task = asyncio.create_task(self._run_journald_collector())
            self._collector_tasks.append(task)

        # Start file tailer collector task if enabled
        if self.config.sources.files.enabled:
            task = asyncio.create_task(self._run_file_collector())
            self._collector_tasks.append(task)

    def raise_if_failed(self) -> None:
        """Surface dead collectors/ticker to the supervisor instead of false ONLINE."""
        tasks = list(self._collector_tasks)
        if self.aggregator._ticker_task is not None:
            tasks.append(self.aggregator._ticker_task)
        for task in tasks:
            if task.done() and not task.cancelled():
                error = task.exception()
                if error is not None:
                    raise RuntimeError(f"Monitoring task failed: {error}") from error
                if self._running:
                    raise RuntimeError("Monitoring task stopped unexpectedly")

    async def stop(self) -> None:
        """Gracefully stop all collectors and flush buffers."""
        self._running = False
        for task in self._collector_tasks:
            task.cancel()

        await asyncio.gather(*self._collector_tasks, return_exceptions=True)
        await self.journald_collector.stop()
        await self.file_collector.stop()
        await self.aggregator.stop()

    async def _run_journald_collector(self) -> None:
        try:
            async for entry in self.journald_collector.stream():
                if not self._running:
                    break
                await self.ingest_log(entry)
        except asyncio.CancelledError:
            pass

    async def _run_file_collector(self) -> None:
        try:
            async for entry in self.file_collector.stream():
                if not self._running:
                    break
                await self.ingest_log(entry)
        except asyncio.CancelledError:
            pass

    async def ingest_log(self, entry: LogEntry) -> Optional[Incident]:
        """Evaluate single log line: prefilter and buffer into aggregator."""
        # Observe successful authentication before noise filtering; never trust
        # a behavior field supplied by an external log producer.
        entry.metadata.pop("behavior", None)
        evidence = self.behavior.observe(entry)
        if evidence is not None:
            entry.metadata["behavior"] = evidence
            if evidence["anomalies"]:
                return await self.aggregator.add_entry(entry, Category.ANOMALY)
        should_analyze, category_hint = self.prefilter.should_analyze(entry)
        if not should_analyze or category_hint is None:
            return None

        return await self.aggregator.add_entry(entry, category_hint)

    async def process_incident(self, incident: Incident) -> Optional[Alert]:
        """Evaluate an aggregated incident through memory and LLM, dispatching alerts if needed."""
        # 1. Fast Structural Rule Check (Pattern, Service, IP)
        suppressed, rule = False, None
        if self.config.memory.enabled and incident.category_hint != Category.ANOMALY:
            suppressed, rule = self.memory_matcher.evaluate_fast_suppression(incident)
        if suppressed and rule:
            # Suppressed without invoking LLM!
            verdict = LLMVerdict(
                alert_needed=False,
                severity=Severity.LOW,
                category=incident.category_hint,
                title=f"Suppressed by rule: {rule.content}",
                summary=f"Incident in service {incident.service} automatically suppressed by memory rule {rule.id}",
                matched_memory_rule=rule.id,
                reasoning=f"Matched fast memory rule: {rule.content} (Rule ID: {rule.id})",
            )
            alert = Alert(
                status=AlertStatus.AUTO_SUPPRESSED,
                incident=incident,
                verdict=verdict,
                suppression_reason=f"Matched memory rule: {rule.content}",
            )
            self.memory_store.save_alert(alert)
            return alert

        # 2. Extract Semantic Context for LLM
        semantic_context = ""
        if self.config.memory.enabled:
            semantic_context = self.memory_matcher.get_semantic_prompt_context(
                max_rules=self.config.memory.max_semantic_rules_in_prompt
            )

        # Record the evidence before inference, including interrupted analyses.
        pending = Alert(incident=incident, verdict=LLMVerdict(
            title="Analysis pending", summary="Inference has not completed; review original evidence.",
            confidence=0.0, category=incident.category_hint))
        self.memory_store.save_alert(pending)
        # 3. Consult LLM
        verdict = await self.llm_client.analyze(incident, memory_context=semantic_context)

        if verdict.matched_memory_rule:
            from logsentinel.core.models import MemoryRuleType
            allowed = self.memory_store.list_rules(active_only=True, rule_type=MemoryRuleType.SEMANTIC)[:self.config.memory.max_semantic_rules_in_prompt] if self.config.memory.enabled else []
            if verdict.matched_memory_rule not in {rule.id for rule in allowed}:
                verdict = verdict.model_copy(update={
                    "alert_needed": True, "matched_memory_rule": None,
                    "reasoning": "Unverified memory rule claimed by LLM; manual review required.",
                })

        # Check if LLM marked it as suppressed by user instructions or benign
        if not verdict.alert_needed:
            alert = Alert(
                id=pending.id,
                status=AlertStatus.AUTO_SUPPRESSED,
                incident=incident,
                verdict=verdict,
                suppression_reason=verdict.reasoning or "Classified as benign or suppressed by LLM memory instructions",
            )
            self.memory_store.save_alert(alert)
            return alert

        # 4. Create Alert and Dispatch
        alert = Alert(
            id=pending.id,
            status=AlertStatus.NEW,
            incident=incident,
            verdict=verdict,
        )

        # Persist before external I/O: cancellation cannot erase the incident.
        self.memory_store.save_alert(alert)
        channels = await self.dispatcher.dispatch(alert)
        alert.channels_notified = channels
        alert.status = AlertStatus.NOTIFIED if channels else AlertStatus.NEW

        # Save to database
        self.memory_store.save_alert(alert)

        # Fire callback if registered
        if self.on_alert_callback:
            await self.on_alert_callback(alert)

        return alert

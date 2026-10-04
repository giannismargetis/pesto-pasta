"""Marshal bus events from worker threads onto the Qt GUI thread."""

from PySide6.QtCore import QObject, Signal

from ..events import EventBus, Level, Preview, Settings, Status


class UiBridge(QObject):
    status = Signal(object)
    level = Signal(float)
    preview = Signal(object)
    settings = Signal(object)
    custom = Signal(object)  # extension events (e.g. PASTA plan updates)

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        # Signals emitted from other threads are delivered via queued connections.
        bus.subscribe(self.status.emit, Status)
        bus.subscribe(lambda e: self.level.emit(e.rms), Level)
        bus.subscribe(self.preview.emit, Preview)
        bus.subscribe(self.settings.emit, Settings)
        bus.subscribe(self._other)

    def _other(self, event: object) -> None:
        if not isinstance(event, (Status, Level, Preview, Settings)):
            self.custom.emit(event)

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from tracey.img import ExportResult, execute_jobs
from tracey.store import ExportProfile


class ExportWorker(QThread):
    exported = Signal(object)

    def __init__(
        self,
        jobs: list[tuple[Path, ExportProfile]],
        output_dir: Path,
        masks: dict[Path, Path] | None = None,
        shadows: dict[Path, Path] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.jobs = jobs
        self.output_dir = output_dir
        self.masks = masks or {}
        self.shadows = shadows or {}

    def run(self) -> None:
        execute_jobs(
            self.jobs,
            self.output_dir,
            self.report,
            self.masks,
            self.isInterruptionRequested,
            self.shadows,
        )

    def report(self, result: ExportResult) -> bool:
        self.exported.emit(result)
        return not self.isInterruptionRequested()

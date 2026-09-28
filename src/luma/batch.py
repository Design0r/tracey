from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from luma import img
from luma.store import ExportProfile


class ExportWorker(QThread):
    exported = Signal(object)

    def __init__(
        self,
        files: list[Path],
        profile: ExportProfile,
        output_dir: Path,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.files = files
        self.profile = profile
        self.output_dir = output_dir

    def run(self) -> None:
        img.execute_profile(self.files, self.profile, self.output_dir, self.report)

    def report(self, result: img.ExportResult) -> bool:
        self.exported.emit(result)
        return not self.isInterruptionRequested()

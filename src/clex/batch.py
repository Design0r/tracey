from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from clex import img
from clex.store import ExportProfile


class ExportWorker(QThread):
    exported = Signal(object)

    def __init__(
        self,
        files: list[Path],
        profile: ExportProfile,
        output_dir: Path,
        masks: dict[Path, Path] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.files = files
        self.profile = profile
        self.output_dir = output_dir
        self.masks = masks or {}

    def run(self) -> None:
        img.execute_profile(
            self.files,
            self.profile,
            self.output_dir,
            self.report,
            self.masks,
            self.isInterruptionRequested,
        )

    def report(self, result: img.ExportResult) -> bool:
        self.exported.emit(result)
        return not self.isInterruptionRequested()

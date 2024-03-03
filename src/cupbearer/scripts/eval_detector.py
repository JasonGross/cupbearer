from pathlib import Path

from cupbearer.detectors import AnomalyDetector
from cupbearer.tasks import Task
from cupbearer.utils.scripts import script


@script
def main(
    task: Task,
    detector: AnomalyDetector,
    save_path: Path | str | None,
    pbar: bool = False,
    batch_size: int = 1024,
):
    detector.set_model(task.model)

    detector.eval(
        train_dataset=task.trusted_data,
        test_dataset=task.test_data,
        pbar=pbar,
        save_path=save_path,
        batch_size=batch_size,
    )

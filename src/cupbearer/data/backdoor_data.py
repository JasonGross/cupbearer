# This needs to be in a separate file from backdoors.py because of circularity issues
# with the config groups. See __init__.py.
from dataclasses import dataclass

from cupbearer.data import DatasetConfig
from cupbearer.data.backdoors import Backdoor
from cupbearer.data.transforms import Transform
from cupbearer.utils.config_groups import config_group


@dataclass
class BackdoorData(DatasetConfig):
    original: DatasetConfig = config_group(DatasetConfig)
    backdoor: Backdoor = config_group(Backdoor)

    def __post_init__(self):
        # Pass no_augmentation arg down to original if possible
        if hasattr(super(), "__post_init__"):
            super().__post_init__()
        if self.no_augmentation:
            try:
                self.original.no_augmentation = self.no_augmentation
            except AttributeError:
                pass

    @property
    def num_classes(self):
        return self.original.num_classes

    def get_transforms(self) -> list[Transform]:
        # We can't set this in __post_init__, since then the backdoor would be part of
        # transforms in the config that's stored to disk. If we then load this config,
        # another backdoor would be added to the transforms.
        transforms = []
        transforms += self.original.get_transforms()
        transforms += super().get_transforms()
        transforms += [self.backdoor]
        return transforms

    def _build(self):
        return self.original._build()

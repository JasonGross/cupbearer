from abc import ABC, abstractmethod
from dataclasses import dataclass

from cupbearer.utils.config_groups import register_config_group
from cupbearer.utils.scripts import load_config
from cupbearer.utils.utils import BaseConfig, PathConfigMixin, load, mutable_field

from .computations import Model, cnn, mlp


@dataclass(kw_only=True)
class ModelConfig(BaseConfig, ABC):
    @abstractmethod
    def build_model(self) -> Model:
        pass

    def build_params(self):
        return None


@dataclass
class StoredModel(ModelConfig, PathConfigMixin):
    def build_model(self) -> Model:
        model_cfg = load_config(self.get_path(), "model", ModelConfig)

        return model_cfg.build_model()

    def build_params(self):
        return load(self.get_path() / "model")["params"]


@dataclass
class MLP(ModelConfig):
    output_dim: int = 10
    hidden_dims: list[int] = mutable_field([256, 256])

    def build_model(self) -> Model:
        return Model(mlp(output_dim=self.output_dim, hidden_dims=self.hidden_dims))

    def setup_and_validate(self):
        super().setup_and_validate()
        if self.debug:
            # TODO: we need at least two layers here because abstractions currently
            # only work in that case. Abstraction implementation should be fixed.
            self.hidden_dims = [2, 2]


@dataclass
class CNN(ModelConfig):
    output_dim: int = 10
    channels: list[int] = mutable_field([32, 64])
    dense_dims: list[int] = mutable_field([256, 256])

    def build_model(self) -> Model:
        return Model(
            cnn(
                output_dim=self.output_dim,
                channels=self.channels,
                dense_dims=self.dense_dims,
            )
        )

    def setup_and_validate(self):
        super().setup_and_validate()
        if self.debug:
            self.channels = [2]
            self.dense_dims = [2]


MODELS = {
    "mlp": MLP,
    "cnn": CNN,
    "from_run": StoredModel,
}

register_config_group(ModelConfig, MODELS)

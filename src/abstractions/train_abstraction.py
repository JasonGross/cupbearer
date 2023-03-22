# based on the flax example code

from collections import defaultdict
import sys
import jax
import jax.numpy as jnp
import numpy as np
from flax import linen as nn

from flax.training import train_state
import optax
from loguru import logger
import argparse
from clearml import Task

from abstractions import abstraction, data, train_mnist, utils


@jax.jit
def apply_model(state, batch, forward_fn):
    """Computes gradients, loss and metrics for a single batch."""

    images, labels, backdoored = batch
    logits, activations = forward_fn(images)

    def loss_fn(params):
        abstractions, predicted_abstractions, predicted_logits = state.apply_fn(
            {"params": params}, activations
        )
        assert isinstance(abstractions, list)
        assert isinstance(predicted_abstractions, list)
        assert len(abstractions) == len(predicted_abstractions)
        b, d = abstractions[0].shape
        assert predicted_abstractions[0].shape == (b, d)
        assert logits.shape == (b, 10) == predicted_logits.shape

        # Output loss (KL divergence between actual and predicted output):
        output_loss = (logits.exp() * (logits - predicted_logits)).sum(axis=-1).mean()
        # Consistency loss:
        consistency_loss = 0
        # Skip the first abstraction, since there's no prediction for that
        # TODO: I don't think this can be jitted right now because it depends on the length
        # of the list. Either figure out how to specialize on that, or see if I can
        # move the for loop into the compiled code instead of unrolling (not sure this
        # works for lists). Or maybe just change things so I'm using arrays instead
        # of lists everywhere. It's not like this actually needs to be dynamic.
        for abstraction, predicted_abstraction in zip(
            abstractions[1:], predicted_abstractions
        ):
            consistency_loss += (abstraction - predicted_abstraction).square().mean()

        consistency_loss /= len(predicted_abstractions)

        loss = output_loss + consistency_loss

        return loss, (output_loss, consistency_loss)

    grad_fn = jax.value_and_grad(loss_fn, has_aux=True)
    (loss, (output_loss, consistency_loss)), grads = grad_fn(state.params)

    metrics = {
        "loss": loss,
        "output_loss": output_loss,
        "consistency_loss": consistency_loss,
    }
    return grads, metrics


@jax.jit
def update_model(state, grads):
    return state.apply_gradients(grads=grads)


def train_epoch(state, train_loader, rng, metrics_logger, forward_fn):
    """Train for a single epoch."""
    train_ds_size = len(train_loader.dataset)
    steps_per_epoch = train_ds_size // train_loader.batch_size

    epoch_metrics = defaultdict(list)

    for batch in train_loader:
        grads, metrics = apply_model(state, batch, forward_fn)
        state = update_model(state, grads)
        for k, v in metrics.items():
            epoch_metrics[k].append(v)
            metrics_logger.report_scalar(
                title="Training", series=k, value=v.item(), iteration=int(state.step)
            )

    train_metrics = {k: np.mean(v) for k, v in epoch_metrics.items()}
    return state, train_metrics


def create_train_state(rng, config):
    """Creates initial `TrainState`."""
    model = abstraction.Abstraction(config.abstract_dim, 10)
    params = model.init(
        rng,
        # Activations of the default MLP: input, then 2 hidden layers
        # TODO: should get the shapes dynamically by running the MLP once
        [
            jnp.ones([1, 28 * 28]),
            jnp.ones([1, 256]),
            jnp.ones([1, 256]),
        ],
    )["params"]
    tx = optax.sgd(config.learning_rate, config.momentum)
    return train_state.TrainState.create(apply_fn=model.apply, params=params, tx=tx)


def train_and_evaluate(config) -> train_state.TrainState:
    """Execute model training and evaluation loop.

    Args:
      config: Hyperparameter configuration for training and evaluation.

    Returns:
      The train state (which includes the `.params`).
    """
    if config.debug:
        jax_config.update("jax_debug_nans", True)
        jax_config.update("jax_disable_jit", True)
        config.no_clearml = True

    if config.no_clearml:
        metrics_logger = utils.DummyLogger()
    else:
        # seeds pytorch and numpy
        Task.set_random_seed(0)
        task = Task.init(
            project_name="backdoor-detection", task_name="train MNIST abstraction"
        )
        metrics_logger = task.get_logger()

    train_loader, test_loader = data.get_data_loaders(config.batch_size)
    rng = jax.random.PRNGKey(0)

    rng, init_rng = jax.random.split(rng)
    state = create_train_state(init_rng, config)

    model = train_mnist.MLP()
    params = utils.load(config.model_path)
    # We're not jitting this because it's only used in the apply_model function,
    # which is jitted.
    forward_fn = lambda x: model.apply(params, x, return_activations=True)

    for epoch in range(1, config.num_epochs + 1):
        rng, input_rng = jax.random.split(rng)
        metrics_logger.report_scalar("epoch", "epoch", epoch, int(state.step))
        state, train_metrics = train_epoch(
            state, train_loader, input_rng, metrics_logger, forward_fn
        )
        test_batch = next(iter(test_loader))
        _, test_metrics = apply_model(state, test_batch)

        logger.log(
            "METRICS",
            "epoch:% 3d, train_loss: %.4f, train_accuracy: %.2f, test_loss: %.4f, test_accuracy: %.2f"
            % (
                epoch,
                train_metrics["loss"],
                train_metrics["accuracy"] * 100,
                test_metrics["loss"],
                test_metrics["accuracy"] * 100,
            ),
        )

    return state


def parse_args():
    parser = argparse.ArgumentParser(description="Jax MNIST training example")
    parser.add_argument(
        "--num_epochs", type=int, default=10, help="Number of epochs to train"
    )
    parser.add_argument("--batch_size", type=int, default=128, help="Batch size")
    parser.add_argument(
        "--learning_rate", type=float, default=0.1, help="Learning rate"
    )
    parser.add_argument("--momentum", type=float, default=0.9, help="Momentum")
    parser.add_argument("--abstract_dim", type=int, default=256, help="Abstract dim")
    parser.add_argument("--model_path", type=str, help="Path to model", required=True)
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--no_clearml", action="store_true", help="Disable ClearML")
    parser.add_argument(
        "--workdir", type=str, default="logs", help="Directory for logs"
    )
    return parser.parse_args()


def main():
    logger.remove()
    logger.level("METRICS", no=25, color="<green>", icon="📈")
    logger.add(
        sys.stderr, format="{level.icon} <level>{message}</level>", level="METRICS"
    )
    # Default logger for everything else:
    logger.add(sys.stderr, filter=lambda record: record["level"].name != "METRICS")
    config = parse_args()
    train_and_evaluate(config)


if __name__ == "__main__":
    main()
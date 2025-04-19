# A rework of 'optimization.py' from the original HF diffusers repo, modified to call the
# actual pytorch scheduler these are based on - providing a much bigger set of tuning params

# coding=utf-8
# Copyright 2022 The HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""PyTorch optimizations for diffusion models."""

import math
import traceback
from enum import Enum
from typing import Optional, Union, List

from diffusers import DEISMultistepScheduler, UniPCMultistepScheduler, DDPMScheduler
from diffusers.utils import logging
from torch.optim import Optimizer
from torch.optim.lr_scheduler import (
    LambdaLR,
    ConstantLR,
    LinearLR,
    CosineAnnealingLR,
    CosineAnnealingWarmRestarts,
)
logger = logging.get_logger(__name__)


class SchedulerType(Enum):
    LINEAR = "linear"
    LINEAR_WITH_WARMUP = "linear_with_warmup"
    COSINE = "cosine"
    COSINE_ANNEALING = "cosine_annealing"
    COSINE_ANNEALING_WITH_RESTARTS = "cosine_annealing_with_restarts"
    COSINE_WITH_RESTARTS = "cosine_with_restarts"
    POLYNOMIAL = "polynomial"
    CONSTANT = "constant"
    CONSTANT_WITH_WARMUP = "constant_with_warmup"
    REX = "rex",
    RISE = "rise_inverse_sigmoid_engine"

def get_rise_scheduler(
    optimizer,
    num_training_steps,
    max_lr,
    min_lr
    ):
    """
    Returns a learning rate scheduler based on the RISE (Relative Inverted Sigmoid Engine) algorithm.

    Args:
        optimizer (Optimizer): The optimizer to use for training.
        num_training_steps (int): The total number of training steps.
        max_lr (float): The maximum learning rate.
        min_lr (float): The minimum learning rate.
    
    Returns:
        A LambdaLR scheduler that adjusts the learning rate according to the RISE algorithm.
    """
    def lr_lambda(current_step):
        pct = current_step / num_training_steps

        # Phase 1: Linear warmup (0%–10%)
        if pct < 0.10:
            return min_lr + (max_lr - min_lr) * (pct / 0.10)

        # Phase 2: Constant (10%–15%)
        elif pct < 0.15:
            return max_lr

        # Phase 3: First inverted sigmoid (15%–57.5%)
        elif pct < 0.575:
            t = (pct - 0.15) / (0.55 - 0.15)  # remap to [0, 1]
            curve = (1 - t) / (1 + 8 * t)  # smooth tail, 8 controls steepness
            return min_lr + (max_lr - min_lr) * curve

        # Phase 4: Second inverted sigmoid (55%–100%)
        else:
            t = (pct - 0.55) / (1.0 - 0.55)  # remap to [0, 1]
            curve = (1 - t) / (1 + 20 * t)  # sharper fall, 20 makes this steeper
            return min_lr + (max_lr - min_lr) * curve

    return LambdaLR(optimizer, lr_lambda)


def get_rex_scheduler(
    optimizer: Optimizer, 
    num_training_steps: int, 
    num_warmup_steps
    ):
    """
    Returns a learning rate scheduler based on the REx (Relative Exploration) algorithm.

    Args:
        optimizer (Optimizer): The optimizer to use for training.
        total_training_steps (int): The total number of training steps.

    Returns:
        A tuple containing the original optimizer object and a lambda function that can be used to create a PyTorch learning rate scheduler.
    """
    def lr_lambda(current_step: int):
        # https://arxiv.org/abs/2107.04197
        max_lr = 1
        min_lr = 0.00000001
        d = 0.9

        if current_step < num_warmup_steps:
            return max(min_lr, float(current_step) / float(max(1, num_warmup_steps)))
        elif current_step < num_training_steps:
            progress = current_step / num_training_steps
            div = (1 - d) + (d * (1 - progress))
            return min_lr + (max_lr - min_lr) * ((1 - progress) / div)
        else:
            return min_lr

    return LambdaLR(optimizer, lr_lambda)


# region Newer Schedulers
def get_cosine_annealing_scheduler(
        optimizer: Optimizer, max_iter: int = 500, eta_min: float = 1e-6
):
    """
    Adjust LR from initial rate to the minimum specified LR over the maximum number of steps.
    See <a href='https://miro.medium.com/max/828/1*Bk4xhtvg_Su42GmiVtvigg.webp'> for an example.
    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        max_iter (`int`, *optional*, defaults to 500):
            The number of steps for the warmup phase.
        eta_min (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.

    Return:
        `torch.optim.lr_scheduler.CosineAnnealingLR` with the appropriate schedule.
    """
    return CosineAnnealingLR(optimizer, T_max=max_iter, eta_min=eta_min)


def get_cosine_annealing_warm_restarts_scheduler(
        optimizer: Optimizer, t_0: int = 25, t_mult: int = 1, eta_min: float = 1e-6
):
    """
    Adjust LR from initial rate to the minimum specified LR over the maximum number of steps.
    See <a href='https://miro.medium.com/max/828/1*Bk4xhtvg_Su42GmiVtvigg.webp'> for an example.
    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        t_0 (`int`, *optional*, defaults to 25):
            Number of iterations for the first restart.
        t_mult (`int`, *optional*, defaults to 1):
            A factor increases number of iterations after a restart. Default: 1.
        eta_min ('float', *optional*, defaults to 1e-6)
            The minimum learning rate to adjust to.

    Return:
        `torch.optim.lr_scheduler.CosineAnnealingWarmRestarts` with the appropriate schedule.
    """
    return CosineAnnealingWarmRestarts(
        optimizer, T_0=t_0, T_mult=t_mult, eta_min=eta_min
    )


def get_linear_schedule(
        optimizer: Optimizer, start_factor: float = 0.5, total_iters: int = 500
):
    """
    Create a schedule with a learning rate that decreases at a linear rate until it reaches the number of total iters,
    after which it will run at a constant rate.
    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        start_factor (`float`, *optional*, defaults to 0.5):
            The value the LR will be multiplied by at the start of training.
        total_iters ('int', *optional*, defaults to 500):
            The epoch number at which the LR will be adjusted

    Return:
        `torch.optim.lr_scheduler.LinearLR` with the appropriate schedule.

    """

    return LinearLR(optimizer, start_factor=start_factor, total_iters=total_iters)


def get_constant_schedule(
        optimizer: Optimizer, factor: float = 1.0, total_iters: int = 500
):
    """
    Create a schedule with a constant learning rate, using the learning rate set in optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        factor (`float`, *optional*, defaults to 2.0):
            The value the step will be divided by when total_iters is reached.
        total_iters ('int', *optional*, defaults to 500):
            The epoch number at which the LR will be adjusted

    Return:
        `torch.optim.lr_scheduler.ConstantLR` with the appropriate schedule.
    """
    return ConstantLR(optimizer, factor=factor, total_iters=total_iters)


# endregion

# region originals
def get_constant_schedule_with_warmup(
        optimizer: Optimizer, num_warmup_steps: int, min_lr: float
):
    """
    Create a schedule with a constant learning rate preceded by a warmup period during which the learning rate
    increases linearly between 0 and the initial lr set in the optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        num_warmup_steps (`int`):
            The number of steps for the warmup phase.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.

    Return:
        `torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.
    """

    def lr_lambda(current_step: int):
        if current_step < num_warmup_steps:
            lamb = float(current_step) / float(max(1, num_warmup_steps))
            return max(min_lr, lamb)
        return 1.0

    return LambdaLR(optimizer, lr_lambda, last_epoch=-1)


def get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps, num_training_steps, min_lr, last_epoch=-1
):
    """
    Create a schedule with a learning rate that decreases linearly from the initial lr set in the optimizer to 0, after
    a warmup period during which it increases linearly from 0 to the initial lr set in the optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        num_warmup_steps (`int`):
            The number of steps for the warmup phase.
        num_training_steps (`int`):
            The total number of training steps.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.
        last_epoch (`int`, *optional*, defaults to -1):
            The index of the last epoch when resuming training.


    Return:
        `torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.
    """

    def lr_lambda(current_step: int):
        if current_step < num_warmup_steps:
            return max(min_lr, float(current_step) / float(max(1, num_warmup_steps)))
        return max(
            0.0,
            float(num_training_steps - current_step)
            / float(max(1, num_training_steps - num_warmup_steps)),
        )

    return LambdaLR(optimizer, lr_lambda, last_epoch)


def get_cosine_schedule_with_warmup(
        optimizer: Optimizer,
        num_warmup_steps: int,
        num_training_steps: int,
        min_lr: float,
        num_cycles: float = 0.5,
        last_epoch: int = -1,
):
    """
    Create a schedule with a learning rate that decreases following the values of the cosine function between the
    initial lr set in the optimizer to 0, after a warmup period during which it increases linearly between 0 and the
    initial lr set in the optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        num_warmup_steps (`int`):
            The number of steps for the warmup phase.
        num_training_steps (`int`):
            The total number of training steps.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.
        num_cycles (`float`, *optional*, defaults to 0.5):
            The number of waves in the cosine schedule (the defaults is to just decrease from the max value to 0
            following a half-cosine).
        last_epoch (`int`, *optional*, defaults to -1):
            The index of the last epoch when resuming training.

    Return:
        `torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.
    """

    def lr_lambda(current_step):
        if current_step < num_warmup_steps:
            return max(min_lr, float(current_step) / float(max(1, num_warmup_steps)))
        progress = float(current_step - num_warmup_steps) / float(
            max(1, num_training_steps - num_warmup_steps)
        )
        return max(
            0.0, 0.5 * (1.0 + math.cos(math.pi * float(num_cycles) * 2.0 * progress))
        )

    return LambdaLR(optimizer, lr_lambda, last_epoch)


def get_cosine_with_hard_restarts_schedule_with_warmup(
        optimizer: Optimizer,
        num_warmup_steps: int,
        num_training_steps: int,
        min_lr: float,
        num_cycles: int = 1,
        last_epoch: int = -1,
):
    """
    Create a schedule with a learning rate that decreases following the values of the cosine function between the
    initial lr set in the optimizer to 0, with several hard restarts, after a warmup period during which it increases
    linearly between 0 and the initial lr set in the optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        num_warmup_steps (`int`):
            The number of steps for the warmup phase.
        num_training_steps (`int`):
            The total number of training steps.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.
        num_cycles (`int`, *optional*, defaults to 1):
            The number of hard restarts to use.
        last_epoch (`int`, *optional*, defaults to -1):
            The index of the last epoch when resuming training.

    Return:
        `torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.
    """

    def lr_lambda(current_step):
        if current_step < num_warmup_steps:
            return max(min_lr, float(current_step) / float(max(1, num_warmup_steps)))
        progress = float(current_step - num_warmup_steps) / float(
            max(1, num_training_steps - num_warmup_steps)
        )
        if progress >= 1.0:
            return 0.0
        return max(
            0.0,
            0.5 * (1.0 + math.cos(math.pi * ((float(num_cycles) * progress) % 1.0))),
        )

    return LambdaLR(optimizer, lr_lambda, last_epoch)

def get_polynomial_decay_schedule_with_warmup(
        optimizer,
        num_warmup_steps,
        num_training_steps,
        min_lr: float,
        lr_end=1e-7,
        power=1.0,
        last_epoch=-1,
):
    """
    Create a schedule with a learning rate that decreases as a polynomial decay from the initial lr set in the
    optimizer to end lr defined by *lr_end*, after a warmup period during which it increases linearly from 0 to the
    initial lr set in the optimizer.

    Args:
        optimizer ([`~torch.optim.Optimizer`]):
            The optimizer for which to schedule the learning rate.
        num_warmup_steps (`int`):
            The number of steps for the warmup phase.
        num_training_steps (`int`):
            The total number of training steps.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.
        lr_end (`float`, *optional*, defaults to 1e-7):
            The end LR.
        power (`float`, *optional*, defaults to 1.0):
            Power factor.
        last_epoch (`int`, *optional*, defaults to -1):
            The index of the last epoch when resuming training.

    Note: *power* defaults to 1.0 as in the fairseq implementation, which in turn is based on the original BERT
    implementation at
    https://github.com/google-research/bert/blob/f39e881b169b9d53bea03d2d341b31707a6c052b/optimization.py#L37

    Return:
        `torch.optim.lr_scheduler.LambdaLR` with the appropriate schedule.

    """

    lr_init = optimizer.defaults["lr"]
    if not (lr_init > lr_end):
        raise ValueError(
            f"lr_end ({lr_end}) must be be smaller than initial lr ({lr_init})"
        )

    def lr_lambda(current_step: int):
        if current_step < num_warmup_steps:
            return max(min_lr, float(current_step) / float(max(1, num_warmup_steps)))
        elif current_step > num_training_steps:
            return lr_end / lr_init  # as LambdaLR multiplies by lr_init
        else:
            lr_range = lr_init - lr_end
            decay_steps = num_training_steps - num_warmup_steps
            pct_remaining = 1 - (current_step - num_warmup_steps) / decay_steps
            decay = lr_range * pct_remaining ** power + lr_end
            return decay / lr_init  # as LambdaLR multiplies by lr_init

    return LambdaLR(optimizer, lr_lambda, last_epoch)


# endregion


def get_scheduler(
        name: Union[str, SchedulerType],
        optimizer: Optimizer,
        num_warmup_steps: Optional[int] = None,
        total_training_steps: Optional[int] = None,
        min_lr: float = 1e-6,
        min_lr_scale: float = 0,
        num_cycles: int = 1,
        power: float = 1.0,
        factor: float = 0.5,
        scale_pos: float = 0.5,
        unet_lr: float = 1.0,
        tenc_lr: float = 1.0,
):
    """
    Unified API to get any scheduler from its name.

    Args:
        name (`str` or `SchedulerType`):
            The name of the scheduler to use.
        optimizer (`torch.optim.Optimizer`):
            The optimizer that will be used during training.
        num_warmup_steps (`int`, *optional*):
            The number of warmup steps. This is not required by all schedulers (hence the argument being
            optional), the function will raise an error if it's unset and the scheduler type requires it.
        total_training_steps (`int``, *optional*):
            The number of training steps. This is not required by all schedulers (hence the argument being
            optional), the function will raise an error if it's unset and the scheduler type requires it.
        min_lr (`float`, *optional*, defaults to 1e-6):
            The minimum learning rate to use after the number of max iterations is reached.
        min_lr_scale('float', Target learning rate / min learning rate)
        num_cycles (`int`, *optional*):
            The number of hard restarts used in `COSINE_WITH_RESTARTS` scheduler.
        power (`float`, *optional*, defaults to 1.0):
            Power factor. See `POLYNOMIAL` scheduler
        factor ('float', *optional*, defaults to 0.5):
            Multiplication factor for constant and linear schedulers
        scale_pos (`float`, *optional*, defaults to 0.5):
            If a lr scheduler has an adjustment point, this is the percentage of training steps at which to
            adjust the LR.
        unet_lr (`float`, *optional*, defaults to 1e-6):
            The learning rate used to control d-dadaption for the UNET
        tenc_lr (`float`, *optional*, defaults to 1e-6):
            The learning rate used to control d-dadaption for the TENC


    """
    name = SchedulerType(name)
    break_steps = int(total_training_steps * scale_pos)

    # Newer schedulers
    if name == SchedulerType.CONSTANT:
        return get_constant_schedule(optimizer, factor, break_steps)

    if name == SchedulerType.LINEAR:
        return get_linear_schedule(optimizer, factor, break_steps)

    if name == SchedulerType.COSINE_ANNEALING:
        return get_cosine_annealing_scheduler(optimizer, break_steps, min_lr)

    if name == SchedulerType.COSINE_ANNEALING_WITH_RESTARTS:
        return get_cosine_annealing_warm_restarts_scheduler(
            optimizer, int(break_steps / 2), eta_min=min_lr
        )
    if name == SchedulerType.REX:
        return get_rex_scheduler(
            optimizer, num_training_steps=total_training_steps, num_warmup_steps=num_warmup_steps
        )
    if name == SchedulerType.RISE:
        return get_rise_scheduler(
            optimizer, num_training_steps=total_training_steps, max_lr=unet_lr, min_lr=min_lr
        )

    # OG schedulers
    if name == SchedulerType.CONSTANT_WITH_WARMUP:
        return get_constant_schedule_with_warmup(
            optimizer, num_warmup_steps=num_warmup_steps, min_lr=min_lr_scale
        )

    if name == SchedulerType.LINEAR_WITH_WARMUP:
        return get_linear_schedule_with_warmup(
            optimizer, num_warmup_steps, total_training_steps, min_lr=min_lr_scale
        )

    if name == SchedulerType.COSINE_WITH_RESTARTS:
        return get_cosine_with_hard_restarts_schedule_with_warmup(
            optimizer,
            num_warmup_steps=num_warmup_steps,
            num_training_steps=total_training_steps,
            min_lr=min_lr_scale,
            num_cycles=num_cycles,
        )
    if name == SchedulerType.POLYNOMIAL:
        return get_polynomial_decay_schedule_with_warmup(
            optimizer,
            num_warmup_steps=num_warmup_steps,
            num_training_steps=total_training_steps,
            min_lr=min_lr_scale,
            power=power,
        )
    if name == SchedulerType.COSINE:
        return get_cosine_schedule_with_warmup(
            optimizer,
            num_warmup_steps=num_warmup_steps,
            num_training_steps=total_training_steps,
            min_lr=min_lr_scale,
            num_cycles=num_cycles,
        )
        
class UniversalScheduler:
    def __init__(
            self,
            name: Union[str, SchedulerType],
            optimizer: Optional[Optimizer],
            num_warmup_steps: int,
            total_training_steps: int,
            total_epochs: int,
            num_cycles: int = 1,
            power: float = 1.0,
            factor: float = 0.5,
            min_lr: float = 1e-6,
            scale_pos: float = 0.5,
            unet_lr: float = 1.0,
            tenc_lr: float = 1.0,
    ):
        self.current_step = 0
        og_schedulers = [
            "constant_with_warmup",
            "linear_with_warmup",
            "cosine",
            "cosine_with_restarts",
            "polynomial",
        ]

        self.is_torch_scheduler = name in og_schedulers

        self.total_steps = total_training_steps if not self.is_torch_scheduler else total_epochs

        self.scheduler = get_scheduler(
            name=name,
            optimizer=optimizer,
            num_warmup_steps=num_warmup_steps,
            total_training_steps=total_training_steps,
            min_lr=min_lr,
            num_cycles=num_cycles,
            power=power,
            factor=factor,
            scale_pos=scale_pos,
            unet_lr=unet_lr,
            tenc_lr=tenc_lr,
        )

    def step(self, steps: int = 1, is_epoch: bool = False):
        if self.is_torch_scheduler and is_epoch:
            self.current_step += steps
            self.scheduler.step(self.current_step)
        else:
            self.current_step += steps
            self.scheduler.step(self.current_step)

    def state_dict(self) -> dict:
        return self.scheduler.state_dict()

    def load_state_dict(self, state_dict: dict) -> None:
        self.scheduler.load_state_dict(state_dict)

    def get_last_lr(self) -> List[float]:
        return self.scheduler.get_last_lr()

    def get_lr(self) -> float:
        return self.scheduler.get_lr()


# Temp conditional for dadapt optimizer console logging
def log_dadapt(disable: bool = True):
    if disable:
        return 0
    else:
        return 5


def get_optimizer(optimizer: str, learning_rate: float, weight_decay: float, params_to_optimize, lr_warmup_steps: int, num_train_epochs: int,):
    try:
        if optimizer == "Adafactor":
            from transformers.optimization import Adafactor
            return Adafactor(
                params_to_optimize,
                lr=learning_rate,
                clip_threshold=1.0,
                decay_rate=-0.8,
                weight_decay=weight_decay,
                relative_step=True,
                scale_parameter=True,
                warmup_init=False,
            )

        elif optimizer == "CAME":
            from pytorch_optimizer import CAME
            return CAME(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                weight_decouple=True,
                fixed_decay=False,
                clip_threshold=1.0,
                ams_bound=False,
            )

        elif optimizer == "8bit AdamW":
            from bitsandbytes.optim import AdamW8bit
            return AdamW8bit(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
            )

        elif optimizer == "RAdam":
            from pytorch_optimizer import RAdam
            return RAdam(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                betas=(0.9, 0.999),
                weight_decouple=True,
                fixed_decay=False,
                n_sma_threshold=5,
                degenerated_to_sgd=False,
                r=0.95,
                adanorm=False,
                adam_debias=False,
                eps=1e-8,
            )

        elif optimizer == "PAdam":
            from pytorch_optimizer import PAdam
            return PAdam(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                betas=(0.9, 0.999),
                weight_decouple=True,
                fixed_decay=False,
                eps=1e-8,
                partial=0.25,
            )

        elif optimizer == "Ranger":
            from pytorch_optimizer import Ranger
            return Ranger(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                alpha=0.5,
                k=6,
                n_sma_threshold=5,
                betas=(0.95, 0.999),
                eps=1e-5,
                use_gc=True, 
                gc_conv_only=False,
            )

        elif optimizer == "Ranger21":
            from pytorch_optimizer import Ranger21
            return Ranger21(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                num_iterations=num_train_epochs,
                beta0=0.9,
                betas=(0.9, 0.999),
                use_softplus=True,
                beta_softplus=50.0,
                warm_down_min_lr=3e-5,
                agc_clipping_value=1e-2,
                agc_eps=1e-3,
                centralize_gradients=True,
                normalize_gradients=True,
                lookahead_merge_time=5,
                lookahead_blending_alpha=0.5,
                weight_decouple=True,
                fixed_decay=False,
                norm_loss_factor=1e-4,
                adam_debias=False,
                eps=1e-8,
            )

        elif optimizer == "QHAdam":
            from pytorch_optimizer import QHAdam
            return QHAdam(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                betas=(0.9, 0.999),
                nus=(1.0, 1.0),
                weight_decouple=True,
                fixed_decay=False,
                eps=1e-8,
            )

        elif optimizer == "Yogi":
            from pytorch_optimizer import Yogi
            return Yogi(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                betas=(0.9, 0.999),
                weight_decouple=True,
                fixed_decay=False,
                r=0.95,
                adanorm=False,
                adam_debias=False,
                eps=1e-3,
                initial_accumulator=1e-6,
            )

        elif optimizer == "Paged 8bit AdamW":
            from bitsandbytes.optim import PagedAdamW8bit
            return PagedAdamW8bit(
                params_to_optimize,
                lr=learning_rate,
                betas=(0.9, 0.999),
                eps=1e-8,
                weight_decay=weight_decay,
                percentile_clipping=100,
                block_wise=True,
                amsgrad=False,
                args=None,
                optim_bits=32,
                min_8bit_size=4096,
            )

        elif optimizer == "Apollo":
            from pytorch_optimizer import Apollo
            return Apollo(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                warmup_steps=lr_warmup_steps,
                weight_decay_type="l2",
                rebound="constant",
                eps=1e-4,
                beta=0.9,
            )
            
        elif optimizer == "Lion":
            from pytorch_optimizer import Lion
            return Lion(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                weight_decouple=True,
                fixed_decay=False,
                use_gc=False,
                adanorm=False,
            )

        elif optimizer == "8bit Lion":
            from bitsandbytes.optim import Lion8bit
            return Lion8bit(
                params_to_optimize,
                lr=learning_rate,
                betas=(0.9, 0.99),
                weight_decay=weight_decay,
                is_paged=False,
                percentile_clipping=100,
                block_wise=True,
                min_8bit_size=4096,
            )

        elif optimizer == "Paged 8bit Lion":
            from bitsandbytes.optim import PagedLion8bit
            return PagedLion8bit(
                params_to_optimize,
                lr=learning_rate,
                betas=(0.9, 0.99),
                weight_decay=0,
                percentile_clipping=100,
                block_wise=True,
                min_8bit_size=4096,
            )

        elif optimizer == "AdamW Dadaptation":
            from dadaptation import DAdaptAdam
            return DAdaptAdam(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                decouple=True,
                use_bias_correction=True,
                log_every=log_dadapt(True),
                fsdp_in_use=False,
            )

        elif optimizer == "Lion Dadaptation":
            from dadaptation import DAdaptLion
            return DAdaptLion(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                log_every=log_dadapt(True),
                fsdp_in_use=False,
                d0=0.000001,
            )

        elif optimizer == "Adan Dadaptation":
            from dadaptation import DAdaptAdan
            return DAdaptAdan(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                log_every=log_dadapt(True),
                no_prox=False,
                d0=0.000001,
            )
        
        elif optimizer == "AdanIP Dadaptation":
            from dadaptation.experimental import DAdaptAdanIP
            return DAdaptAdanIP(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                log_every=log_dadapt(True),
                no_prox=False,
                d0=0.000001
            )
        
        elif optimizer == "SGD Dadaptation":
            from dadaptation import DAdaptSGD
            return DAdaptSGD(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                log_every=log_dadapt(True),
                momentum=0.0,
                fsdp_in_use=False,
                d0=0.000001,
            )
            
        elif optimizer == "Prodigy":
            from pytorch_optimizer import Prodigy
            return Prodigy(
                params_to_optimize,
                lr=learning_rate,
                weight_decay=weight_decay,
                safeguard_warmup=False,
                d0=1e-6,
                d_coef=1.0,
                bias_correction=False,
                fixed_decay=False,
                weight_decouple=True,
                )
                
        elif optimizer == "Tiger":
            from pytorch_optimizer import Tiger
            return Tiger(
                params_to_optimize,
                lr=learning_rate,
                beta=0.965,
                weight_decay=weight_decay,
                weight_decouple=True,
                fixed_decay=False,
            )

    except Exception as e:
        logger.warning(f"Exception importing {optimizer}: {e}")
        traceback.print_exc()
        print(str(e))
        print("WARNING: Using default optimizer (AdamW from Torch)")
        optimizer = "Torch AdamW"

    from torch.optim import AdamW
    return AdamW(
        params_to_optimize,
        lr=learning_rate,
        weight_decay=weight_decay,
    )


def get_noise_scheduler(args):
    if args.noise_scheduler == "DEIS":
        scheduler_class = DEISMultistepScheduler

    elif args.noise_scheduler == "UniPC":
        scheduler_class = UniPCMultistepScheduler

    else:
        scheduler_class = DDPMScheduler

    return scheduler_class.from_pretrained(
        args.get_pretrained_model_name_or_path(), subfolder="scheduler"
    )

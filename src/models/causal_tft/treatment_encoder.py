from abc import ABC, abstractmethod
from torch import nn
from torch import Tensor
import torch
from torch.nn import functional as F

from src.models.causal_tft.tft_core import TFTBackbone
from src.models.causal_tft.utils import create_sequential_layers


class AbstractTreatmentModule(nn.Module, ABC):
    def __init__(
        self,
        theta_backbone: TFTBackbone,
        e0_backbone: TFTBackbone,
        treatment_max_value: int,
        hidden_size: int,
        last_nn: list[int],
    ):
        super().__init__()
        self.theta_backbone = theta_backbone
        self.e0_backbone = e0_backbone
        self.treatment_max_value = treatment_max_value
        self.theta_head = create_sequential_layers(last_nn, hidden_size, 2 ** treatment_max_value)
        self.e0_head = create_sequential_layers(last_nn, hidden_size, 2 ** treatment_max_value)

        # This flag is used to know if we are training theta or m0/e0
        self.training_theta = False

    def forward(self, windows_batch: dict[str, Tensor], tau: Tensor):

        if self.training:
            if self.training_theta:
                with torch.no_grad():
                    e0 = self.encode_e0_values(self.e0_head(self.e0_backbone.get_z(windows_batch, tau)))
                theta = self.theta_head(self.theta_backbone.get_z(windows_batch, tau))
            else:
                e0 = self.encode_e0_values(self.e0_head(self.e0_backbone.get_z(windows_batch, tau)))
                with torch.no_grad():
                    theta = torch.ones_like(e0)
        else:
            with torch.no_grad():
                e0 = self.encode_e0_values(self.e0_head(self.e0_backbone.get_z(windows_batch, tau)))
                theta = self.theta_head(self.theta_backbone.get_z(windows_batch, tau))

        return e0, theta

    def encode_e0_values(self, e0: Tensor) -> Tensor:
        return e0

    @abstractmethod
    def encode_treatments(self, y_shape: tuple[int, ...], treatments: Tensor, e0_compare: bool = True) -> Tensor:
        raise NotImplementedError

    @abstractmethod
    def loss_e0(self, encoded_treatments: Tensor, e0: Tensor) -> Tensor:
        raise NotImplementedError


class OneHotTreatmentModule(AbstractTreatmentModule):

    def __init__(
        self,
        theta_backbone: TFTBackbone,
        e0_backbone: TFTBackbone,
        treatment_max_value: int,
        hidden_size: int,
        last_nn: list[int],
    ):
        super().__init__(theta_backbone, e0_backbone, treatment_max_value, hidden_size, last_nn)
        self.classification_loss = nn.functional.cross_entropy
        self.e0_norm_function = nn.Softmax(dim=2)

    def encode_treatments(self, y_shape: tuple[int, ...], treatments: Tensor, e0_compare: bool = True):
        encoded_treatments = torch.zeros(y_shape, device=treatments.device)
        for k in range(self.treatment_max_value):
            encoded_treatments += treatments[:, :, -1 - k].clone().unsqueeze(-1) * (2 ** k)

        if not e0_compare:
            encoded_treatments = encoded_treatments[:, :, 0].long()
            encoded_treatments = F.one_hot(encoded_treatments, 2 ** self.treatment_max_value).float()

        return encoded_treatments

    def encode_e0_values(self, e0: Tensor) -> Tensor:
        if self.training and not self.training_theta:
            return e0
        else:
            return self.e0_norm_function(e0)

    def loss_e0(self, encoded_treatments: Tensor, e0: Tensor):
        return self.classification_loss(
            e0.reshape(-1, 2 ** self.treatment_max_value),
            encoded_treatments.flatten().long(),
            reduction="none"
        )


class CumulativeTreatmentModule(AbstractTreatmentModule):
    def __init__(
        self,
        theta_backbone: TFTBackbone,
        e0_backbone: TFTBackbone,
        treatment_max_value: int,
        hidden_size: int,
        last_nn: list[int],
    ):
        super().__init__(theta_backbone, e0_backbone, treatment_max_value, hidden_size, last_nn)
        self.classification_loss = nn.functional.binary_cross_entropy
        self.eps = 1e-7
        self.e0_norm_function = nn.Softmax(dim=2)

    def encode_treatments(self, y_shape: tuple[int, ...], treatments: Tensor, e0_compare: bool = True):
        encoded_treatments = torch.zeros(y_shape, device=treatments.device)
        for k in range(self.treatment_max_value):
            encoded_treatments += treatments[:, :, -1 - k].clone().unsqueeze(-1) * (2 ** k)

        encoded_treatments = encoded_treatments[:, :, 0].long()
        encoded_treatments = F.one_hot(encoded_treatments, 2 ** self.treatment_max_value).float()
        encoded_treatments = 1 - torch.cumsum(encoded_treatments, dim=-1)

        return encoded_treatments

    def encode_e0_values(self, e0: Tensor) -> Tensor:
        e0 = self.e0_norm_function(e0)
        e0 = 1 - torch.cumsum(e0, dim=-1)
        e0 = e0 - self.eps
        e0 = F.relu(e0)

        return e0

    def loss_e0(self, encoded_treatments: Tensor, e0: Tensor):
        loss = torch.sum(self.classification_loss(e0, encoded_treatments, reduction="none"), dim=-1)
        return loss.flatten()


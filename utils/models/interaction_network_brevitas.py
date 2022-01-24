"""Source: https://github.com/kf7lsu/interaction_network_paper/blob/brevitas_quantized/models/interaction_network.py"""

import torch
import torch_geometric
from torch import Tensor

import torch.nn as nn
import torch.nn.functional as F
import torch_geometric.transforms as T
from torch_geometric.nn import MessagePassing
from torch.nn import Sequential as Seq, Linear, ReLU, Sigmoid
from brevitas.nn import QuantLinear, QuantReLU, QuantSigmoid
from brevitas.core.function_wrapper import TensorClamp
from brevitas.quant.base import *
from brevitas.quant.solver.weight import WeightQuantSolver
from brevitas.quant.solver.bias import BiasQuantSolver
from brevitas.quant.solver.act import ActQuantSolver
from brevitas.quant.solver.trunc import TruncQuantSolver
from brevitas.inject import ExtendedInjector
from brevitas.inject.enum import ScalingImplType, StatsOp, RestrictValueType

#BIT_WIDTH=18

class CustomFloatScaling(ExtendedInjector):
    """
    """
    scaling_per_output_channel = False
    restrict_scaling_type = RestrictValueType.FP
    #bit_width=BIT_WIDTH

class CustomUintActQuant(UintQuant, ParamFromRuntimePercentileScaling, CustomFloatScaling, ActQuantSolver):
    """
    """
    #bit_width=BIT_WIDTH
    tensor_clamp_impl = TensorClamp
    requires_input_bit_width = True

class CustomUintWeightQuant(NarrowIntQuant, MaxStatsScaling, CustomFloatScaling, WeightQuantSolver):
    """
    """
    #bit_width=BIT_WIDTH
    tensor_clamp_impl = TensorClamp
    requires_input_bit_width = True

class RelationalModel(nn.Module):
    def __init__(self, input_size, output_size, hidden_size, bit_width):
        super(RelationalModel, self).__init__()

        self.layers = nn.Sequential(
            QuantLinear(input_size, hidden_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
            QuantReLU(bit_width=bit_width, return_quant_tensor=False),
            QuantLinear(hidden_size, hidden_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
            QuantReLU(bit_width=bit_width, return_quant_tensor=False),
            QuantLinear(hidden_size, output_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
        )

    def forward(self, m):
        return self.layers(m)

class ObjectModel(nn.Module):
    def __init__(self, input_size, output_size, hidden_size, bit_width):
        super(ObjectModel, self).__init__()

        self.layers = nn.Sequential(
            QuantLinear(input_size, hidden_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
            QuantReLU(bit_width=bit_width, return_quant_tensor=False),
            QuantLinear(hidden_size, hidden_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
            QuantReLU(bit_width=bit_width, return_quant_tensor=False),
            QuantLinear(hidden_size, output_size, bias=False, weight_bit_width=bit_width, return_quant_tensor=False),
        )

    def forward(self, C):
        return self.layers(C)


class InteractionNetwork(MessagePassing):
    def __init__(self, aggr='add', flow='source_to_target', hidden_size=40, bit_width=18):
        super(InteractionNetwork, self).__init__(aggr='add',
                                                 flow='source_to_target')
        self.R1 = RelationalModel(10, 4, hidden_size, bit_width=bit_width)
        self.O = ObjectModel(7, 3, hidden_size,bit_width=bit_width)
        self.R2 = RelationalModel(10, 1, hidden_size,bit_width=bit_width)
        self.E: Tensor = Tensor()
        self.forwardSig = QuantSigmoid(return_quant_tensor=False, bit_width=bit_width)

    #def forward(self, x: Tensor, edge_index: Tensor, edge_attr: Tensor) -> Tensor:
    def forward(self, data):
        x = data.x
        edge_index, edge_attr = data.edge_index, data.edge_attr
        # propagate_type: (x: Tensor, edge_attr: Tensor)
        x_tilde = self.propagate(edge_index=edge_index, x=x, edge_attr=edge_attr, size=None)

        m2 = torch.cat([x_tilde[edge_index[1]],
                        x_tilde[edge_index[0]],
                        self.E], dim=1)
        #return torch.sigmoid(self.R2(m2))
        return self.forwardSig(self.R2(m2))

    def message(self, x_i, x_j, edge_attr):
        # x_i --> incoming
        # x_j --> outgoing
        m1 = torch.cat([x_i, x_j, edge_attr], dim=1)
        self.E = self.R1(m1)
        return self.E

    def update(self, aggr_out, x):
        c = torch.cat([x, aggr_out], dim=1)
        return self.O(c)
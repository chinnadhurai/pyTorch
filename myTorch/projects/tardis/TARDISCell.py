import torch
import torch.nn as nn
import numpy as np
from myTorch.utils.gumbel import gumbel_softmax, gumbel_sigmoid
from myTorch.utils import utils

from torch.autograd import Variable


class TARDISCell(nn.Module):

    def __init__(self, input_size, hidden_size, micro_state_size=64, num_mem_cells=8, activation=None, use_gpu=False, batch_size=1):

        super(TARDISCell, self).__init__()

        self.use_gpu = use_gpu

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.micro_state_size = micro_state_size
        self.num_mem_cells = num_mem_cells

        self.W_x2i = nn.Parameter(torch.Tensor(input_size, hidden_size))
        self.W_h2i = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.W_c2i = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.b_i = nn.Parameter(torch.Tensor(hidden_size))

        self.W_x2f = nn.Parameter(torch.Tensor(input_size, hidden_size))
        self.W_h2f = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.W_c2f = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.b_f = nn.Parameter(torch.Tensor(hidden_size))

        self.W_x2o = nn.Parameter(torch.Tensor(input_size, hidden_size))
        self.W_h2o = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.W_c2o = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.b_o = nn.Parameter(torch.Tensor(hidden_size))

        self.W_x2c = nn.Parameter(torch.Tensor(input_size, hidden_size))
        self.W_h2c = nn.Parameter(torch.Tensor(hidden_size, hidden_size))
        self.b_c = nn.Parameter(torch.Tensor(hidden_size))

        # memory related parameters
        self.read_loc_list = None
        self.all_ones = None
        self.all_ones_created = False
        self.num_cells_written_so_far = 0

        self.W_m2i = nn.Parameter(torch.Tensor(micro_state_size, hidden_size))
        self.W_m2f = nn.Parameter(torch.Tensor(micro_state_size, hidden_size))
        self.W_m2o = nn.Parameter(torch.Tensor(micro_state_size, hidden_size))
        self.W_m2c = nn.Parameter(torch.Tensor(micro_state_size, hidden_size))
        self.memory2hidden_params = [self.W_m2i, self.W_m2f, self.W_m2o, self.W_m2c]

        self.W_g_h = nn.Parameter(torch.Tensor(hidden_size, num_mem_cells))
        self.W_g_x = nn.Parameter(torch.Tensor(input_size, num_mem_cells))
        self.W_g_m = nn.Parameter(torch.Tensor(num_mem_cells, num_mem_cells))
        self.W_g_u = nn.Parameter(torch.Tensor(num_mem_cells, num_mem_cells))
        self.logit_params = [self.W_g_h, self.W_g_x, self.W_g_m, self.W_g_u]

        self.W_m = nn.Parameter(torch.Tensor(hidden_size, micro_state_size))
        self.b_m = nn.Parameter(torch.Tensor(micro_state_size))

        self.w_a_h = nn.Parameter(torch.Tensor(hidden_size, 1))
        self.w_b_h = nn.Parameter(torch.Tensor(hidden_size, 1))

        self.w_a_x = nn.Parameter(torch.Tensor(input_size, 1))
        self.w_b_x = nn.Parameter(torch.Tensor(input_size, 1))

        self.w_a_r = nn.Parameter(torch.Tensor(micro_state_size, 1))
        self.w_b_r = nn.Parameter(torch.Tensor(micro_state_size, 1))
        self.alpha_beta_params = [self.w_a_h, self.w_b_h, self.w_a_x, self.w_b_x, self.w_a_r, self.w_b_r]
        self.reset_parameters()

    def _variable(self, input, gpu=None, volatile=False, requires_grad=True):
        use_gpu = gpu if gpu is not None else self.use_gpu
        v = utils.my_variable(input, use_gpu, volatile=volatile, requires_grad=requires_grad)
        return v

    def forward(self, input, last_hidden):
        batch_size = input.size()[0]

        if not self.read_loc_list:
            self.read_loc_list = [self._variable(torch.zeros((batch_size, self.num_mem_cells))).detach()]
        if "mem" not in last_hidden:
            last_hidden["mem"] = self._variable(torch.zeros(batch_size, self.num_mem_cells, self.micro_state_size))

        # compute read weights
        last_hidden_micro_state = torch.mm(last_hidden["h"], self.W_m) + self.b_m
        last_hidden_micro_state = torch.unsqueeze(last_hidden_micro_state, 2)

        # Compute read vector
        m_logits = torch.mm(torch.squeeze(torch.bmm(last_hidden["mem"], last_hidden_micro_state), 2), self.W_g_m)
        h_logits = torch.mm(last_hidden["h"], self.W_g_h)
        x_logits = torch.mm(input, self.W_g_x)
        usage_vector = torch.sum(torch.stack(self.read_loc_list, 1), 1)
        usage_vector = torch.nn.functional.softmax(usage_vector).view_as(usage_vector)
        u_logits = torch.mm(usage_vector, self.W_g_u)
        logits = m_logits + h_logits + x_logits + u_logits

        sampled_one_hot_location = gumbel_softmax(logits, use_gpu=self.use_gpu)
        self.read_loc_list.append(sampled_one_hot_location.detach())
        sampled_mirco_state = torch.bmm(torch.unsqueeze(sampled_one_hot_location, 1), last_hidden["mem"])
        sampled_micro_state = torch.squeeze(sampled_mirco_state, 1)

        self.W_i = torch.cat((self.W_x2i, self.W_h2i, self.W_c2i, self.W_m2i), 0)
        self.W_f = torch.cat((self.W_x2f, self.W_h2f, self.W_c2f, self.W_m2f), 0)
        self.W_o = torch.cat((self.W_x2o, self.W_h2o, self.W_c2o, self.W_m2o), 0)

        alpha = torch.mm(last_hidden["h"], self.w_a_h) + torch.mm(input, self.w_a_x) + torch.mm(sampled_micro_state, self.w_a_r)
        alpha = gumbel_sigmoid(alpha, 0.3, use_gpu=self.use_gpu).repeat(last_hidden["h"].size())
        beta = torch.mm(last_hidden["h"], self.w_b_h) + torch.mm(input, self.w_b_x) + torch.mm(sampled_micro_state, self.w_b_r)
        beta = gumbel_sigmoid(beta, 0.3, use_gpu=self.use_gpu).repeat(last_hidden["h"].size())

        c_input = torch.cat((input, last_hidden["h"], last_hidden["c"], sampled_micro_state), 1)
        i = torch.sigmoid(torch.mm(c_input, self.W_i) + self.b_i)
        f = torch.sigmoid(torch.mm(c_input, self.W_f) + self.b_f)

        cp = torch.mm(input, self.W_x2c) + alpha * torch.mm(last_hidden["h"], self.W_h2c) + beta * torch.mm(sampled_micro_state, self.W_m2c) + self.b_c
        cp = torch.tanh(cp)
        c = f * last_hidden["c"] + i * cp

        o_input = torch.cat((input, last_hidden["h"], c, sampled_micro_state), 1)
        o = torch.sigmoid(torch.mm(o_input, self.W_o) + self.b_o)

        h = o * torch.tanh(c)

        # writing into memory
        curr_micro_state = torch.mm(h, self.W_m) + self.b_m
        curr_micro_state = torch.unsqueeze(curr_micro_state, 1)

        def one_hot(num):
            o = np.zeros((batch_size, self.num_mem_cells, 1))
            o[:, num] = 1
            return o

        def inverse_one_hot(mask):
            if not self.all_ones_created:
                self.all_ones = self._variable(torch.ones(mask.size()))
                self.all_ones_created = True
            return (self.all_ones - mask)

        if self.num_cells_written_so_far < self.num_mem_cells:
            one_hot_mask = self._variable(torch.Tensor(one_hot(self.num_cells_written_so_far)))
            inverse_hot_mask = inverse_one_hot(one_hot_mask)
            self.num_cells_written_so_far += 1
        else:
            one_hot_mask = torch.unsqueeze(sampled_one_hot_location, -1)
            inverse_hot_mask = inverse_one_hot(one_hot_mask)

        memory_matrix = curr_micro_state.repeat(1,self.num_mem_cells,1) * one_hot_mask + last_hidden["mem"] * inverse_hot_mask

        hidden = {}
        hidden["h"] = h
        hidden["c"] = c
        hidden["mem"] = memory_matrix
        return hidden

    def reset_hidden(self):
        hidden = {}
        hidden["h"] = self._variable(torch.Tensor(np.zeros((1, self.hidden_size))))
        hidden["c"] = self._variable(torch.Tensor(np.zeros((1, self.hidden_size))))
        return hidden

    def reset_parameters(self):

        nn.init.xavier_normal(self.W_x2i)
        nn.init.xavier_normal(self.W_x2f)
        nn.init.xavier_normal(self.W_x2o)
        nn.init.xavier_normal(self.W_x2c)
        nn.init.xavier_normal(self.W_m)

        for param in self.alpha_beta_params:
            nn.init.xavier_normal(param)

        for param in self.logit_params:
            nn.init.xavier_normal(param)

        for param in self.memory2hidden_params:
            nn.init.xavier_normal(param)

        nn.init.orthogonal(self.W_h2i)
        nn.init.orthogonal(self.W_h2f)
        nn.init.orthogonal(self.W_h2o)
        nn.init.orthogonal(self.W_h2c)

        nn.init.orthogonal(self.W_c2i)
        nn.init.orthogonal(self.W_c2f)
        nn.init.orthogonal(self.W_c2o)

        nn.init.constant(self.b_i, 0)
        nn.init.constant(self.b_f, 1)
        nn.init.constant(self.b_o, 0)
        nn.init.constant(self.b_c, 0)
        nn.init.constant(self.b_m, 0)

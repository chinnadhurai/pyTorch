import torch
import torch.nn as nn
from torch.autograd import Variable

def sample_gumbel(input, eps=1e-10):
    noise = torch.rand(input.size())
    noise.add_(eps).log_().neg_()
    noise.add_(eps).log_().neg_()
    return Variable(noise)


def gumbel_softmax_sample(logits, temperature):
    """ Draw a sample from the Gumbel-Softmax distribution"""
    y = logits + sample_gumbel(logits)
    return torch.nn.functional.softmax(y / temperature).view_as(y)


def gumbel_sigmoid(logits, temperature=1.0):
    y = logits + sample_gumbel(logits)
    return torch.sigmoid(y / temperature).view_as(y)


def gumbel_softmax(logits, temperature=1, hard=True):
    """Sample from the Gumbel-Softmax distribution and optionally discretize.
    Args:
      logits: [batch_size, n_class] unnormalized log-probs
      temperature: non-negative scalar
      hard: if True, take argmax, but differentiate w.r.t. soft sample y
    Returns:
      [batch_size, n_class] sample from the Gumbel-Softmax distribution.
      If hard=True, then the returned sample will be one-hot, otherwise it will
      be a probabilitiy distribution that sums to 1 across classes
    """
    y = gumbel_softmax_sample(logits, temperature)
    y_one_hot = Variable(torch.zeros(y.size()))
    if hard:
	y_one_hot.scatter_(1, torch.max(y,1,keepdim=True)[1], 1)
        y = (y_one_hot - y).detach() + y
    return y

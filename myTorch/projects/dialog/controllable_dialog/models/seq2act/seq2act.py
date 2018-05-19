import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence

class Seq2Act(nn.Module):
    def __init__(
        self, src_emb_dim, src_vocab_size,
        src_hidden_dim, num_acts,
        pad_token_src, bidirectional,
        nlayers_src, dropout_rate):
        """Initialize Language Model."""
        super(Seq2Act, self).__init__()

        self._src_vocab_size = src_vocab_size
        self._src_emb_dim = src_emb_dim
        self._src_hidden_dim = src_hidden_dim
        self._bidirectional = bidirectional
        self._nlayers_src = nlayers_src
        self._pad_token_src = pad_token_src
        self._dropout_rate = dropout_rate
        self._num_acts = num_acts
        
        # Word Embedding look-up table for the soruce
        self._src_embedding = nn.Embedding(
            self._src_vocab_size,
            self._src_emb_dim,
            self._pad_token_src,
        )
        
        # Encoder GRU
        self._encoder = nn.GRU(
            self._src_emb_dim,
            self._src_hidden_dim //2 if self._bidirectional else self._src_hidden_dim,
            self._nlayers_src,
            bidirectional=bidirectional,
            batch_first=True,
        )

        # Projection layer from decoder hidden states to target language vocabulary
        self._decoder2vocab = nn.Linear(self._src_hidden_dim, self._num_acts)

    def forward(self, input_src, src_lengths, is_training):
        # Lookup word embeddings in source and target minibatch
        src_emb = F.dropout(self._src_embedding(input_src), self._dropout_rate, is_training)

        # Pack padded sequence for length masking in encoder RNN (This requires sorting input sequence by length)
        src_emb = pack_padded_sequence(src_emb, src_lengths, batch_first=True)
        
        # Run sequence of embeddings through the encoder GRU
        _, src_h_t = self._encoder(src_emb)

        # extract the last hidden of encoder
        h_t = torch.cat((src_h_t[-1], src_h_t[-2]), 1) if self._bidirectional else src_h_t[-1]
        h_t = F.dropout(h_t, self._dropout_rate, is_training)

        output_logits = self._decoder2vocab(h_t)
        return output_logits

    def register_optimizer(self, optimizer):
        self._optimizer = optimizer

    @property
    def optimizer(self):
        return self._optimizer

    def save(self, save_dir):
        """Saves the model and the optimizer.
        Args:
            save_dir: absolute path to saving dir.
        """

        file_name = os.path.join(save_dir, "model.p")
        torch.save(self.state_dict(), file_name)

        file_name = os.path.join(save_dir, "optim.p")
        torch.save(self.optimizer.state_dict(), file_name)

    def load(self, save_dir):
        """Loads the model and the optimizer.
        Args:
            save_dir: absolute path to loading dir.
        """

        file_name = os.path.join(save_dir, "model.p")
        self.load_state_dict(torch.load(file_name))

        file_name = os.path.join(save_dir, "optim.p")
        self.optimizer.load_state_dict(torch.load(file_name))

    @property
    def num_parameters(self):
        num_params = 0
        for p in self.parameters():
            num_params += p.data.view(-1).size(0)
        return num_params
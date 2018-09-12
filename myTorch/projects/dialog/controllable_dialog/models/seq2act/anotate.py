#!/usr/bin/env python
import numpy as np
import argparse
import logging
import torch
import hashlib
import os
import time
import math

import myTorch
from myTorch.utils import MyContainer, get_optimizer, create_config
from myTorch.utils.logging import Logger
from myTorch.utils.gen_experiment import GenExperiment

from myTorch.projects.dialog.controllable_dialog.data_readers.seq2act_data_reader import Reader
from myTorch.projects.dialog.controllable_dialog.data_readers.opus import OPUS
from myTorch.projects.dialog.controllable_dialog.data_readers.twitter_corpus import Twitter
from myTorch.projects.dialog.controllable_dialog.data_readers.switchboard_corpus import SwitchBoard
from myTorch.projects.dialog.controllable_dialog.data_readers.frames_corpus import Frames
from myTorch.projects.dialog.controllable_dialog.models.seq2act.seq2act import Seq2Act

parser = argparse.ArgumentParser(description="seq2act")
parser.add_argument("--config", type=str, default="config/opus/default.yaml", help="config file path.")
parser.add_argument("--target_config", type=str, default="config/opus/default.yaml", help="config file path.")
parser.add_argument("--force_restart", type=bool, default=False, help="if True start training from scratch.")

def _safe_exp(x):
    try:
        return math.exp(x)
    except:
        return 0.0

def get_dataset(config):
    if config.dataset == "switchboard":
        corpus = SwitchBoard(config)
    if config.dataset == "frames":
        corpus = Frames(config)
    elif config.dataset == "opus":
        corpus = OPUS(config)
    elif config.dataset == "twitter":
        corpus = Twitter(config)
    return corpus


def anotate(config, experiment, model, reader, target_corpus, tr, logger, device):
    
    target_data = target_corpus.raw_data
    start_time = time.time()

    # convert target_corpus_data text to target data.
    def _convert_data(source_data, pad_id, source_id_to_str, target_str_to_id, target_pad_id):
        target_data = []
        for source_text in source_data:
            target_text = []
            #source_text_itr = source_text if type(source_text) == list else source_text.cpu().numpy()   
            for w_id in source_text:
                if source_id_to_str[w_id] in target_str_to_id and w_id != pad_id: 
                    target_text.append(target_str_to_id[source_id_to_str[w_id]])
            if len(target_text) == 0:
                target_text = [target_pad_id]
            target_data.append(target_text)

        target_lens = [len(target_text) for target_text in target_data]
        max_len = np.max(np.array(target_lens))
        for i, target_text in enumerate(target_data):
            if len(target_text) < max_len:
                target_data[i] +=  [target_pad_id]*(max_len - len(target_text))
        return torch.LongTensor(target_data), torch.LongTensor(target_lens)


    
    target_corpus_sources, target_corpus_sources_lens = _convert_data(
                                target_data["sources"], 
                                target_corpus.str_to_id[config.pad],
                                target_corpus.id_to_str,
                                reader.corpus.str_to_id,
                                reader.corpus.str_to_id[config.pad])

    target_corpus_targets, target_corpus_targets_lens = _convert_data(
                                target_data["targets_output"], 
                                target_corpus.str_to_id[config.pad],
                                target_corpus.id_to_str,
                                reader.corpus.str_to_id,
                                reader.corpus.str_to_id[config.pad])

    acts = { "source" : [], "target" : []}
    
    print("Anotating sources...")
    for i in range(target_corpus_sources.shape[0]):
        output_logits = model(
                        target_corpus_sources[i].unsqueeze(0).to(device), 
                        target_corpus_sources_lens[i].unsqueeze(0).to(device),
                        False)
        acts["source"].append(torch.argmax(output_logits, dim=1).item())
    print("Done.. {}".format(time.time()-start_time))

    for i in range(target_corpus_targets.shape[0]):
        output_logits = model(
                        target_corpus_targets[i].unsqueeze(0).to(device), 
                        target_corpus_targets_lens[i].unsqueeze(0).to(device),
                        False)
        acts["target"].append(torch.argmax(output_logits, dim=1).item())
    print("Done targets.. {}".format(time.time()-start_time))

    target_corpus.save_acts("{}_{}".format(config.dataset, len(reader.corpus.act_to_id)), acts)
    

def create_experiment(config, target_config):
    device = torch.device(config.device)
    logging.info("using {}".format(config.device))

    experiment = GenExperiment(config.name, config.save_dir)
    experiment.register(tag="config", obj=config)

    logger=None
    if config.use_tflogger:
        logger = Logger(config.tflog_dir)
        experiment.register("logger", logger)

    torch.manual_seed(config.rseed)

    reader = {}
    corpus = get_dataset(config)
    reader = Reader(config, corpus)

    target_corpus = get_dataset(target_config)

    model = Seq2Act(config.emb_size_src, len(corpus.str_to_id), config.hidden_dim_src, len(corpus.act_to_id),
                    corpus.str_to_id[config.pad], bidirectional=config.bidirectional,
                    nlayers_src=config.nlayers_src, dropout_rate=config.dropout_rate).to(device)
    logging.info("Num params : {}".format(model.num_parameters))

    experiment.register("model", model)

    optimizer = get_optimizer(model.parameters(), config)
    model.register_optimizer(optimizer)

    tr = MyContainer()

    experiment.register("train_statistics", tr)
    return experiment, model, reader, target_corpus, tr, logger, device


def run_experiment(args):
    """Runs the experiment."""

    config = create_config(args.config)
    target_config = create_config(args.target_config)

    logging.info(config.get())

    experiment, model, reader, target_corpus, tr, logger, device = create_experiment(config, target_config)

    experiment.resume("best_model", "model")
    
    anotate(config, experiment, model, reader, target_corpus, tr, logger, device)
    

        
if __name__ == '__main__':
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_experiment(args)
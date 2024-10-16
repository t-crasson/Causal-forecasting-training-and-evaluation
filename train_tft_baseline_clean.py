import torch
import lightning.pytorch as lp
import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from lightning.pytorch.loggers import TensorBoardLogger
from lightning.pytorch import loggers as pl_loggers
from torch.utils.data import DataLoader
import json
import torch.nn as nn
import warnings
import yaml
import numpy as np
import os
import random
warnings.filterwarnings("ignore")
from pytorch_lightning import seed_everything
from src.models.causal_tft.tft_baseline import TFTBaseline
from src.data.mimic_iii.real_dataset import MIMIC3RealDatasetCollection
if __name__=="__main__":
    with open('/home/thomas/fork_causal_transformer/Causal-forecasting-training-and-evaluation/config/dataset/mimic3_real.yaml', 'r') as file:
        config = yaml.safe_load(file)["dataset"]
    seeds = [10,101,1001,10010,10110]
    for i in range(len(seeds)):
        torch.manual_seed(seeds[i])
        torch.cuda.manual_seed(seeds[i])
        np.random.seed(seeds[i])
        random.seed(seeds[i])
        torch.backends.cudnn.benchmark=True
        seed_everything(seeds[i],workers=True)
        torch.multiprocessing.set_start_method("spawn", force=True)
        horizon = 60
        tau = 5
        hidden_size = 128
        batch_size = 64
        embedding_size_stat = []
        embedding_size_future = []
        checkpoint_callback = ModelCheckpoint(filename='{epoch}-{val_loss:.2f}',
                                                                        monitor = "val_loss",
                                                                        mode="min",)
                                                                        #every_n_epochs=1)
        model = TFTBaseline(
            horizon=horizon,
            projection_length=5,
            target_size=1,
            static_features_size=44,
            hidden_size=hidden_size,
            n_heads=8,
            learning_rate=1e-4,
            attn_dropout=0.1,
            dropout=0.1,
            temporal_features_size=28,
            last_nn=[hidden_size],
            static_embedding_sizes=embedding_size_stat,
            temporal_embedding_sizes=embedding_size_future,
            trend_size=1,
            n_att_layers=2,
            n_static_layers=2,
            conv_blocks=2,
            conv_padding_size=64,
            kernel_size=5
        )
        dataset_collection = MIMIC3RealDatasetCollection(
            "data/processed/all_hourly_data.h5",
            min_seq_length=30,
            max_seq_length=60,
            seed=seeds[i],
            max_number=10000,
            split = {"val":0.15,"test":0.15},
            projection_horizon=5,
            autoregressive=True,
            outcome_list = config["outcome_list"],
            vitals = config["vital_list"],
            treatment_list = config["treatment_list"],
            static_list = config["static_list"]
        )

        dataset_collection.process_data_multi_val()
        dataset_collection.process_data_multi_train()
        logger = pl_loggers.TensorBoardLogger(save_dir="./", name="TFT_repro_clean",version = f"baseline_clean_{i}")
        trainer = pl.Trainer(accelerator ="gpu",
                            #strategy='ddp_find_unused_parameters_true',
                            max_epochs = 2,
                            devices = -1,
                            callbacks = checkpoint_callback,
                            logger = logger,
                            deterministic=True,
                            #check_val_every_n_epoch=5
                            )
        train_loader = DataLoader(dataset_collection.train_f_multi, shuffle=True, batch_size=batch_size)
        val_loader = DataLoader(dataset_collection.val_f_multi, batch_size=batch_size)
        trainer.fit(model,train_loader,val_loader)
        break
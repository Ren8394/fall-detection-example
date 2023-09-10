import numpy as np
import pandas as pd
import torch

from pathlib import Path
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset
from typing import Any, Tuple

from .utils import resample, sliding_window, ensure_type

class FallAllD(Dataset):
    
    base_folder = Path.cwd().joinpath(".tmp", "data")
    _RESOURCES = {
        "raw": ("FallAllD.pkl", "202309091733"),
        "train": ("FallAllD_train.pkl", "202309091733"),
        "val": ("FallAllD_val.pkl", "202309091733"),
        "test": ("FallAllD_test.pkl", "202309091733")
    }

    def __init__(
        self, 
        split: str = "train",
        sr: int = 20,
        window: set = (10, 0.5), 
        location: list = ["Wrist"],   
        download: bool = False
    ) -> None:
        
        super().__init__()
        self.download = download
        self.location = location
        # sampling rate in Hz
        self.sr = sr
        # window size in points (seconds * sampling rate)          
        self.window_size = int(window[0] * sr)
        # window stride in points (window size * overlap ratio)
        self.window_stride = int(self.window_size * window[1])

        # check dataset exists
        if not self._check_dataset_exists(self._RESOURCES["raw"][0]):
            raise RuntimeError(
                "FallAllD Dataset not found. \nYou can download it from " +\
                "https://ieee-dataport.org/open-access/fallalld-comprehensive-dataset-human-falls-and-activities-daily-living " +\
                f"extract its and execute python file then move FallAllD.pkl to the {self.base_folder} folder "
            )
        
        if not self._check_dataset_exists(self._RESOURCES["train"][0]) or \
            not self._check_dataset_exists(self._RESOURCES["val"][0]) or \
            not self._check_dataset_exists(self._RESOURCES["test"][0]):
            self.preprocess()

        # process dataset
        self.df = pd.read_pickle(self.base_folder.joinpath(self._RESOURCES[split][0]))

    def __len__(self) -> int:

        return len(self.df)

    def __getitem__(self, idx) -> Tuple[Any, Any]:
        
        acc = self.df.loc[idx, 'Acc']
        acc = torch.tensor(ensure_type(acc), dtype=torch.float32)
        acc = acc.unsqueeze(0)
        x = acc

        label = self.df.loc[idx, 'Fall/ADL']
        y = torch.tensor(label, dtype=torch.float32)

        return x, y

    def _check_dataset_exists(self, filename) -> bool:
        
        if not self.base_folder.exists():
            self.base_folder.mkdir(parents=True, exist_ok=True)
        else:
            if not self.base_folder.joinpath(filename).exists():
                return False
        return True

    def preprocess(self) -> None:
        
        raw = pd.read_pickle(self.base_folder.joinpath(self._RESOURCES["raw"][0]))
        # drop row with NaN value
        raw = raw.dropna()
        raw["Fall/ADL"] = np.nan
        # drop unused columns
        # keep column SubjectID, Device, ActivityID, TrialNo, and Acc	
        raw = raw.drop(columns=["Gyr", "Mag", "Bar"])
        raw = raw.reset_index(drop=True)

        # resample
        raw["Acc"] = raw["Acc"].apply(lambda x: resample(x, 238, self.sr))
        # sliding window
        del_idx = []
        for i, row in raw.iterrows():
            # ADL
            if row["ActivityID"] < 100:
                for win in sliding_window(row["Acc"], self.window_size, self.window_stride):
                    raw.loc[len(raw)] = [
                        row["SubjectID"], 
                        row["Device"], 
                        row["ActivityID"],
                        row["TrialNo"],
                        win,
                        [0, 1]
                    ]
                # add row index to be deleted
                del_idx.append(i)
            # Fall
            else:
                # column Acc extrct only middle 10 seconds (10 * sr)
                start_cutting = int(np.floor((len(row["Acc"]) - self.window_size) / 2))
                end_cutting = int(start_cutting + self.window_size)
                raw.loc[len(raw)] = [
                    row["SubjectID"], 
                    row["Device"], 
                    row["ActivityID"],
                    row["TrialNo"],
                    row["Acc"][start_cutting:end_cutting],
                    [1, 0]
                ]
                # add row index to be deleted
                del_idx.append(i)
        # delete row
        raw = raw.drop(del_idx)

        # select locations
        assert all(loc in list(raw["Device"].unique()) for loc in self.location), \
            f"device_location must be {list(raw['Device'].unique())}, but got {self.location}"
        raw = raw[raw["Device"].isin(self.location)]
        # sort by SubjectID, Device, ActivityID, TrialNo
        raw = raw.sort_values(by=["SubjectID", "Device", "ActivityID", "TrialNo"])
        raw = raw.reset_index(drop=True)

        # split dataset
        train, val = train_test_split(raw, test_size=0.2, random_state=4444)
        val, test = train_test_split(val, test_size=0.5, random_state=4444)
        train = train.reset_index(drop=True)
        val = val.reset_index(drop=True)
        test = test.reset_index(drop=True)

        # save dataset
        train.to_pickle(self.base_folder.joinpath(self._RESOURCES["train"][0]))
        val.to_pickle(self.base_folder.joinpath(self._RESOURCES["val"][0]))
        test.to_pickle(self.base_folder.joinpath(self._RESOURCES["test"][0]))
    
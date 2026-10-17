"""Persist XGBoost inference trees through stable Model IO, excluding RNG state.

See https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html and
https://github.com/dmlc/xgboost/issues/12459. This is an inference export, not a
checkpoint for exactly resuming stochastic training.
"""

from xgboost import Booster


class PortableBooster(Booster):
    def __getstate__(self):
        return {"portable_model": self.save_raw(raw_format="ubj")}

    def __setstate__(self, state):
        if set(state) != {"portable_model"}:
            raise ValueError("Invalid portable XGBoost model state")
        super().__init__(model_file=bytearray(state["portable_model"]))

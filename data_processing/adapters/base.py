from __future__ import annotations

from abc import ABC, abstractmethod
import pandas as pd


class BaseMMPAdapter(ABC):
    """Base adapter for normalizing MMP-specific raw exports."""

    @abstractmethod
    def normalize_installs(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def normalize_events(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def normalize_cost(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

from .base import BaseMMPAdapter
from .appsflyer import AppsFlyerAdapter
from .adjust import AdjustAdapter
from .singular import SingularAdapter


ADAPTER_REGISTRY = {
    "AppsFlyer": AppsFlyerAdapter,
    "Adjust": AdjustAdapter,
    "Singular": SingularAdapter,
}

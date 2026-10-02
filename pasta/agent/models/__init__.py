from ...config import Config
from .base import DecisionModel
from .decider import DeciderPyTorchModel
from .gguf import DeciderGGUFModel
from .mock import MockDecisionModel

__all__ = [
    "DecisionModel",
    "DeciderPyTorchModel",
    "DeciderGGUFModel",
    "MockDecisionModel",
    "create_decision_model",
]


def create_decision_model(cfg: Config) -> DecisionModel:
    runtime = getattr(cfg.agent, "model_runtime", "gpu").lower()
    if runtime == "gguf":
        quant = getattr(cfg.agent, "model_quantization", "Q4_K_M")
        filename = f"decider-2b-v11-{quant}.gguf"
        return DeciderGGUFModel(model_filename=filename)
    elif runtime == "mock":
        return MockDecisionModel()
    else:
        # Default: PyTorch GPU runtime
        model_name = getattr(cfg.agent, "model", "decider-2b")
        model_id = "Mapika/decider-2b" if "2b" in model_name else model_name
        return DeciderPyTorchModel(model_id=model_id)

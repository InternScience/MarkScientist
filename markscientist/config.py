from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from markscientist.harness import ensure_harness_on_path

ensure_harness_on_path()

from agent_base.utils import load_dotenv


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PACKAGE_ROOT / "data"
TRAJECTORY_ROOT = DATA_ROOT / "trajectories"
WORKSPACE_ROOT = DATA_ROOT / "workspaces"


def default_workspace_root(session_id: str) -> Path:
    return (WORKSPACE_ROOT / session_id).expanduser().resolve()


@dataclass
class ModelConfig:
    model_name: str = "gpt-5.4"
    api_key: Optional[str] = None
    api_base: Optional[str] = None


@dataclass
class AgentConfig:
    max_llm_calls: int = 100
    max_runtime_seconds: int = 9000
    max_output_tokens: int = 10000
    max_input_tokens: int = 320000
    max_retries: int = 10
    temperature: float = 0.6
    top_p: float = 0.95
    presence_penalty: float = 1.1


@dataclass
class TrajectoryConfig:
    auto_save: bool = True
    save_dir: Path = field(default_factory=lambda: TRAJECTORY_ROOT)

    def __post_init__(self) -> None:
        if isinstance(self.save_dir, str):
            self.save_dir = Path(self.save_dir)


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    trajectory: TrajectoryConfig = field(default_factory=TrajectoryConfig)
    workspace_root: Optional[Path] = None

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "Config":
        if env_path:
            load_dotenv(env_path)
        else:
            default_env = Path(__file__).resolve().parent.parent / ".env"
            if default_env.exists():
                load_dotenv(default_env)

        default_model = ModelConfig()
        default_agent = AgentConfig()
        default_trajectory = TrajectoryConfig()
        model = ModelConfig(
            model_name=os.getenv("MODEL_NAME", default_model.model_name),
            api_key=os.getenv("API_KEY"),
            api_base=os.getenv("API_BASE"),
        )
        return cls(
            model=model,
            agent=default_agent,
            trajectory=default_trajectory,
        )


_global_config: Optional[Config] = None


def get_config() -> Config:
    global _global_config
    if _global_config is None:
        _global_config = Config.from_env()
    return _global_config


def set_config(config: Config) -> None:
    global _global_config
    _global_config = config

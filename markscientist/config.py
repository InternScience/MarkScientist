from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


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
    save_dir: Path = field(default_factory=lambda: Path("./data/trajectories"))

    def __post_init__(self) -> None:
        if isinstance(self.save_dir, str):
            self.save_dir = Path(self.save_dir)


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    trajectory: TrajectoryConfig = field(default_factory=TrajectoryConfig)
    workspace_root: Optional[Path] = None
    harness_path: Optional[Path] = None

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "Config":
        if env_path:
            _load_dotenv(env_path)
        else:
            default_env = Path(__file__).resolve().parent.parent / ".env"
            if default_env.exists():
                _load_dotenv(default_env)

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

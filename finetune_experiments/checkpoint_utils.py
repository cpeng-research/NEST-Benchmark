from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from finetune_experiments.finetune_data import (
    COMBINED_LANG,
    DATASET_DIR,
    PREDICTIONS_DIR,
    SUPPORTED_FINETUNE_TASKS,
    clean_model_name,
    read_jsonl,
)
from table3_comparative_eval.config import OPEN_SOURCE_MODEL_PATHS
from table3_comparative_eval.utils.io_utils import read_json
from table3_comparative_eval.utils.local_model_utils import (
    LocalGenerationConfig,
    is_mlx_model,
    run_mlx_generation,
    run_torch_generation,
)


SUPPORTED_CHECKPOINT_LANGS = ("en", "zh")
DEFAULT_CHECKPOINT_TASKS = SUPPORTED_FINETUNE_TASKS


def derive_prediction_model_name(checkpoint_dir: Path) -> str:
    return f"finetuned_{clean_model_name(checkpoint_dir.name)}"


def expand_checkpoint_tasks(tasks: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not tasks:
        return DEFAULT_CHECKPOINT_TASKS
    if "all" in tasks:
        return DEFAULT_CHECKPOINT_TASKS
    invalid = [task for task in tasks if task not in SUPPORTED_FINETUNE_TASKS]
    if invalid:
        raise ValueError(f"Unsupported fine-tuning tasks: {', '.join(invalid)}")
    return tuple(tasks)


def expand_checkpoint_langs(lang: str) -> tuple[str, ...]:
    if lang == COMBINED_LANG:
        return SUPPORTED_CHECKPOINT_LANGS
    if lang not in SUPPORTED_CHECKPOINT_LANGS:
        raise ValueError(f"Unsupported fine-tuning language: {lang}")
    return (lang,)


def load_test_records(
    task: str,
    lang: str,
    dataset_dir: Path = DATASET_DIR,
    limit: int = 0,
) -> list[dict[str, Any]]:
    records = []
    for path in candidate_test_dataset_paths(task, lang, dataset_dir):
        if path.exists():
            records = read_jsonl(path)
            break
    if not records:
        raise FileNotFoundError(f"No test dataset found for task={task} lang={lang} under {dataset_dir}")

    selected = [
        record
        for record in records
        if record.get("task") == task
        and record.get("split", "test") == "test"
        and (lang == COMBINED_LANG or record.get("lang") == lang)
    ]
    selected.sort(key=lambda item: (str(item.get("lang", "")), int(item.get("sample_id", -1))))
    if limit:
        return selected[:limit]
    return selected


def candidate_test_dataset_paths(task: str, lang: str, dataset_dir: Path) -> list[Path]:
    paths = []
    if lang != COMBINED_LANG:
        paths.append(dataset_dir / f"{task}_{lang}_template_test.jsonl")
    paths.append(dataset_dir / f"{task}_{COMBINED_LANG}_template_test.jsonl")
    if lang != COMBINED_LANG:
        paths.append(dataset_dir / f"all_{lang}_template_test.jsonl")
    paths.append(dataset_dir / f"all_{COMBINED_LANG}_template_test.jsonl")
    return paths


def prediction_path_for_record(record: dict[str, Any], prediction_model_name: str) -> Path:
    task = str(record["task"])
    condition = str(record.get("condition", "empty"))
    lang = str(record["lang"])
    sample_id = int(record["sample_id"])
    return checkpoint_prediction_dir(task, condition, lang, prediction_model_name) / f"{sample_id}.json"


def checkpoint_prediction_dir(task: str, condition: str, lang: str, prediction_model_name: str) -> Path:
    root = PREDICTIONS_DIR / f"{task}_{condition}" / lang
    exact_dir = root / prediction_model_name
    if "/" not in prediction_model_name and exact_dir.exists():
        return exact_dir
    return root / clean_model_name(prediction_model_name)


def prediction_has_nonempty_response(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = read_json(path)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    return bool(str(data.get("raw_response", "")).strip())


class FineTunedCheckpointGenerator:
    def __init__(
        self,
        checkpoint_dir: Path,
        config: LocalGenerationConfig,
        base_model: str | None = None,
        dtype: str | None = None,
    ) -> None:
        self.checkpoint_dir = checkpoint_dir.resolve()
        self.config = config
        self.raw_base_model = read_checkpoint_base_model(self.checkpoint_dir)
        self.resolved_base_model = resolve_checkpoint_base_model(self.raw_base_model, base_model)
        self._temporary_adapter_dir: tempfile.TemporaryDirectory[str] | None = None
        self.adapter_format = detect_adapter_format(self.checkpoint_dir)
        self.adapter_load_dir = self.checkpoint_dir

        if self.adapter_format == "mlx":
            self.adapter_load_dir = self.prepare_mlx_adapter_load_dir()
            self.model, self.tokenizer = self.load_mlx_adapter()
            self.backend = "mlx"
        elif self.adapter_format == "peft":
            self.model, self.tokenizer, torch_device = self.load_peft_adapter(dtype=dtype)
            self.backend = f"torch_peft_{torch_device}"
        else:
            self.model, self.tokenizer = self.load_full_or_unsloth_checkpoint(dtype=dtype)
            self.backend = "mlx" if is_mlx_model(self.model) else "torch"

    def generate(self, prompt: str, system_prompt: str) -> str:
        if self.backend == "mlx":
            return run_mlx_generation(self.model, self.tokenizer, prompt, system_prompt, self.config)
        return run_torch_generation(self.model, self.tokenizer, prompt, system_prompt, self.config)

    def prepare_mlx_adapter_load_dir(self) -> Path:
        if not self.resolved_base_model or self.resolved_base_model == self.raw_base_model:
            return self.checkpoint_dir

        adapter_config_path = self.checkpoint_dir / "adapter_config.json"
        if not adapter_config_path.exists():
            return self.checkpoint_dir

        self._temporary_adapter_dir = tempfile.TemporaryDirectory(prefix="nest_adapter_")
        temp_dir = Path(self._temporary_adapter_dir.name)
        for child in self.checkpoint_dir.iterdir():
            destination = temp_dir / child.name
            if child.name == "adapter_config.json":
                continue
            safe_link_or_copy(child, destination)

        adapter_config = json.loads(adapter_config_path.read_text(encoding="utf-8"))
        adapter_config["base_model_name_or_path"] = self.resolved_base_model
        (temp_dir / "adapter_config.json").write_text(
            json.dumps(adapter_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return temp_dir

    def load_mlx_adapter(self):
        from mlx_lm import load as mlx_load

        if not self.resolved_base_model:
            raise RuntimeError(f"Cannot load MLX adapter without a base model: {self.checkpoint_dir}")
        return mlx_load(
            self.resolved_base_model,
            adapter_path=str(self.adapter_load_dir),
            tokenizer_config={"trust_remote_code": True},
        )

    def load_peft_adapter(self, dtype: str | None = None):
        import torch

        try:
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PEFT-format adapter detected. Install peft and transformers in this environment, "
                "or convert the adapter to MLX format before using an MLX-only path."
            ) from exc

        if not self.resolved_base_model:
            raise RuntimeError(f"Cannot load PEFT adapter without a base model: {self.checkpoint_dir}")

        device = preferred_torch_device()
        torch_dtype = resolve_torch_dtype(dtype, device)
        model_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "torch_dtype": torch_dtype,
            "local_files_only": self.config.local_files_only,
            "low_cpu_mem_usage": True,
        }
        if device == "cuda":
            model_kwargs["device_map"] = self.config.device_map
            if self.config.load_in_4bit:
                model_kwargs["load_in_4bit"] = True
        elif self.config.load_in_4bit:
            print(
                "PEFT adapter detected on non-CUDA backend; ignoring load_in_4bit because "
                "bitsandbytes 4-bit loading is CUDA-only in this path."
            )

        print(
            "PEFT adapter detected; loading base model with Transformers and applying "
            f"adapter via PEFT. base={self.resolved_base_model} device={device}"
        )
        model = AutoModelForCausalLM.from_pretrained(self.resolved_base_model, **model_kwargs)
        model = PeftModel.from_pretrained(
            model,
            str(self.checkpoint_dir),
            local_files_only=self.config.local_files_only,
        )
        if device != "cuda":
            model = model.to(device)
        model.eval()

        tokenizer_source = self.checkpoint_dir if (self.checkpoint_dir / "tokenizer_config.json").exists() else self.resolved_base_model
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_source,
            trust_remote_code=True,
            local_files_only=self.config.local_files_only,
        )
        if getattr(tokenizer, "pad_token_id", None) is None and getattr(tokenizer, "eos_token", None) is not None:
            tokenizer.pad_token = tokenizer.eos_token
        return model, tokenizer, device

    def load_full_or_unsloth_checkpoint(self, dtype: str | None = None):
        from unsloth import FastLanguageModel

        self.adapter_load_dir = self.prepare_mlx_adapter_load_dir()
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(self.adapter_load_dir),
            max_seq_length=self.config.max_seq_length,
            dtype=dtype,
            load_in_4bit=self.config.load_in_4bit,
            device_map=self.config.device_map,
            local_files_only=self.config.local_files_only,
            trust_remote_code=True,
        )
        FastLanguageModel.for_inference(model)
        return model, tokenizer


def detect_adapter_format(checkpoint_dir: Path) -> str:
    adapter_config_path = checkpoint_dir / "adapter_config.json"
    if not adapter_config_path.exists():
        return "full_or_unknown"

    try:
        config = json.loads(adapter_config_path.read_text(encoding="utf-8"))
    except Exception:
        return "full_or_unknown"

    if "num_layers" in config and "lora_parameters" in config and (checkpoint_dir / "adapters.safetensors").exists():
        return "mlx"
    if "peft_type" in config or (checkpoint_dir / "adapter_model.safetensors").exists():
        return "peft"
    return "full_or_unknown"


def preferred_torch_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def resolve_torch_dtype(dtype: str | None, device: str):
    import torch

    if dtype:
        normalized = dtype.lower()
        if normalized in {"float16", "fp16", "half"}:
            return torch.float16
        if normalized in {"bfloat16", "bf16"}:
            return torch.bfloat16
        if normalized in {"float32", "fp32"}:
            return torch.float32
        raise ValueError(f"Unsupported torch dtype: {dtype}")
    if device in {"cuda", "mps"}:
        return torch.float16
    return torch.float32


def read_checkpoint_base_model(checkpoint_dir: Path) -> str | None:
    metadata_path = checkpoint_dir / "training_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            resolved = metadata.get("resolved_model")
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        except Exception:
            pass

    adapter_config_path = checkpoint_dir / "adapter_config.json"
    if adapter_config_path.exists():
        data = json.loads(adapter_config_path.read_text(encoding="utf-8"))
        base_model = data.get("base_model_name_or_path")
        if isinstance(base_model, str) and base_model.strip():
            return base_model.strip()

    return None


def resolve_checkpoint_base_model(raw_base_model: str | None, override: str | None = None) -> str | None:
    if override:
        return override
    if not raw_base_model:
        return raw_base_model
    if is_existing_or_hub_model(raw_base_model):
        return raw_base_model
    mapped = map_known_base_model(raw_base_model)
    return mapped or raw_base_model


def is_existing_or_hub_model(value: str) -> bool:
    path = Path(value).expanduser()
    if path.exists():
        return True
    if os.path.isabs(value):
        return False
    return "/" in value


def map_known_base_model(value: str) -> str | None:
    normalized = normalize_model_fragment(value)
    alias_fragments = {
        "llama318binstruct": "meta-llama/Llama-3.1-8B-Instruct",
        "metallama318binstruct": "meta-llama/Llama-3.1-8B-Instruct",
        "qwen257binstruct": "Qwen/Qwen2.5-7B-Instruct",
        "gemma29bit": "google/gemma-2-9b-it",
        "mistral7binstructv03": "mistralai/Mistral-7B-Instruct-v0.3",
    }
    for fragment, repo_id in alias_fragments.items():
        if fragment in normalized:
            return repo_id

    for label, repo_id in OPEN_SOURCE_MODEL_PATHS.items():
        for candidate in (label, repo_id, Path(repo_id).name):
            fragment = normalize_model_fragment(candidate)
            if fragment and fragment in normalized:
                return repo_id
    return None


def normalize_model_fragment(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def safe_link_or_copy(source: Path, destination: Path) -> None:
    try:
        destination.symlink_to(source, target_is_directory=source.is_dir())
        return
    except OSError:
        pass

    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)

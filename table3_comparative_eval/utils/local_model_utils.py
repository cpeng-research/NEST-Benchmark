from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from table3_comparative_eval.config import resolve_open_source_model


@dataclass(frozen=True)
class LocalGenerationConfig:
    max_seq_length: int = 8192
    max_new_tokens: int = 2048
    temperature: float = 0.0
    top_p: float = 0.9
    load_in_4bit: bool = True
    local_files_only: bool = False
    raw_prompt: bool = False
    model_path: str | None = None
    device_map: str = "auto"


class LocalUnslothGenerator:
    def __init__(self, model_name: str, config: LocalGenerationConfig):
        from unsloth import FastLanguageModel

        self.model_name = model_name
        self.config = config
        self.resolved_model = resolve_open_source_model(model_name, config.model_path)
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name=self.resolved_model,
            max_seq_length=config.max_seq_length,
            dtype=None,
            load_in_4bit=config.load_in_4bit,
            device_map=config.device_map,
            local_files_only=config.local_files_only,
            trust_remote_code=True,
        )
        FastLanguageModel.for_inference(self.model)
        self.backend = "mlx" if is_mlx_model(self.model) else "torch"

    def generate(self, prompt: str, system_prompt: str) -> str:
        config = self.config
        if self.backend == "torch" and is_gemma_name(self.model_name, self.resolved_model) and not config.raw_prompt:
            print(
                f"local model={self.model_name} backend={self.backend} is Gemma on Torch; "
                "using raw prompt first to avoid empty chat-template generations."
            )
            config = replace(config, raw_prompt=True)

        text = self.generate_once(prompt, system_prompt, config)
        if text or config.raw_prompt:
            return text

        print(
            f"local model={self.model_name} backend={self.backend} produced empty response; "
            "retrying with raw prompt."
        )
        fallback_config = replace(self.config, raw_prompt=True)
        return self.generate_once(prompt, system_prompt, fallback_config)

    def generate_once(self, prompt: str, system_prompt: str, config: LocalGenerationConfig) -> str:
        if self.backend == "mlx":
            return run_mlx_generation(self.model, self.tokenizer, prompt, system_prompt, config)
        return run_torch_generation(self.model, self.tokenizer, prompt, system_prompt, config)


def is_mlx_model(model: Any) -> bool:
    model_module = model.__class__.__module__
    return model_module.startswith("mlx_lm.") or model_module.startswith("mlx.")


def is_gemma_name(model_name: str, resolved_model: str) -> bool:
    return "gemma" in f"{model_name} {resolved_model}".lower()


def is_gemma_tokenizer(tokenizer: Any) -> bool:
    name = str(getattr(tokenizer, "name_or_path", "")).lower()
    class_name = tokenizer.__class__.__name__.lower()
    return "gemma" in name or "gemma" in class_name


def messages_for_prompt(prompt: str, system_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def fallback_messages_for_prompt(prompt: str, system_prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"{system_prompt}\n\n{prompt}"}]


def raw_prompt_text(prompt: str, system_prompt: str) -> str:
    return f"{system_prompt}\n\n{prompt}\n\nAssistant:"


def build_prompt_text(tokenizer: Any, prompt: str, system_prompt: str, raw_prompt: bool) -> str:
    if raw_prompt or not hasattr(tokenizer, "apply_chat_template"):
        return raw_prompt_text(prompt, system_prompt)

    last_error: Exception | None = None
    for messages in (messages_for_prompt(prompt, system_prompt), fallback_messages_for_prompt(prompt, system_prompt)):
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return raw_prompt_text(prompt, system_prompt)


def build_torch_inputs(tokenizer: Any, prompt: str, system_prompt: str, raw_prompt: bool):
    if raw_prompt or not hasattr(tokenizer, "apply_chat_template"):
        return tokenizer(raw_prompt_text(prompt, system_prompt), return_tensors="pt")

    last_error: Exception | None = None
    for messages in (messages_for_prompt(prompt, system_prompt), fallback_messages_for_prompt(prompt, system_prompt)):
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
        except TypeError:
            try:
                return tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_tensors="pt",
                )
            except Exception as exc:
                last_error = exc
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return tokenizer(raw_prompt_text(prompt, system_prompt), return_tensors="pt")


def normalize_torch_inputs(inputs):
    import torch

    if isinstance(inputs, torch.Tensor):
        return {
            "input_ids": inputs,
            "attention_mask": torch.ones_like(inputs),
        }
    return dict(inputs)


def infer_torch_device(model: Any):
    import torch

    if hasattr(model, "device"):
        return model.device

    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cpu")


def run_mlx_generation(model: Any, tokenizer: Any, prompt: str, system_prompt: str, config: LocalGenerationConfig) -> str:
    from mlx_lm import generate as mlx_generate
    from mlx_lm.sample_utils import make_sampler

    prompt_text = build_prompt_text(tokenizer, prompt, system_prompt, config.raw_prompt)
    sampler = make_sampler(temp=config.temperature, top_p=config.top_p)
    return mlx_generate(
        model,
        tokenizer,
        prompt=prompt_text,
        max_tokens=config.max_new_tokens,
        sampler=sampler,
        verbose=False,
    ).strip()


def run_torch_generation(model: Any, tokenizer: Any, prompt: str, system_prompt: str, config: LocalGenerationConfig) -> str:
    import torch

    inputs = build_torch_inputs(tokenizer, prompt, system_prompt, config.raw_prompt)
    inputs = normalize_torch_inputs(inputs)

    device = infer_torch_device(model)
    inputs = {key: value.to(device) for key, value in inputs.items()}
    prompt_length = inputs["input_ids"].shape[-1]

    do_sample = config.temperature > 0
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if pad_token_id is None:
        pad_token_id = eos_token_id
    generation_kwargs = {
        "max_new_tokens": config.max_new_tokens,
        "do_sample": do_sample,
        "pad_token_id": pad_token_id,
        "eos_token_id": eos_token_id,
    }
    if do_sample:
        generation_kwargs.update({"temperature": config.temperature, "top_p": config.top_p})
    if is_gemma_tokenizer(tokenizer):
        generation_kwargs["min_new_tokens"] = min_new_tokens_for_retry(8, config.max_new_tokens)
        begin_suppress_tokens = gemma_begin_suppress_tokens(tokenizer)
        if begin_suppress_tokens:
            generation_kwargs["begin_suppress_tokens"] = begin_suppress_tokens

    with torch.no_grad():
        output_ids = model.generate(**inputs, **generation_kwargs)

    generated_ids = output_ids[0][prompt_length:]
    text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    if text or not is_gemma_tokenizer(tokenizer):
        return text

    print("Gemma Torch generation decoded to empty text; retrying once with sampling and stronger EOS suppression.")
    retry_kwargs = dict(generation_kwargs)
    retry_kwargs.update(
        {
            "do_sample": True,
            "temperature": max(config.temperature, 0.2),
            "top_p": max(config.top_p, 0.95),
            "min_new_tokens": min_new_tokens_for_retry(32, config.max_new_tokens),
            "repetition_penalty": 1.05,
        }
    )
    with torch.no_grad():
        output_ids = model.generate(**inputs, **retry_kwargs)
    generated_ids = output_ids[0][prompt_length:]
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def min_new_tokens_for_retry(preferred: int, max_new_tokens: int) -> int:
    if max_new_tokens <= 0:
        return 0
    return max(1, min(preferred, max_new_tokens))


def gemma_begin_suppress_tokens(tokenizer: Any) -> list[int]:
    tokens: list[int] = []
    for token_id in (
        getattr(tokenizer, "eos_token_id", None),
        token_id_for(tokenizer, "<end_of_turn>"),
    ):
        if isinstance(token_id, int) and token_id >= 0 and token_id not in tokens:
            tokens.append(token_id)
    return tokens


def token_id_for(tokenizer: Any, token: str) -> int | None:
    convert = getattr(tokenizer, "convert_tokens_to_ids", None)
    if not callable(convert):
        return None
    try:
        token_id = convert(token)
    except Exception:
        return None
    return token_id if isinstance(token_id, int) else None

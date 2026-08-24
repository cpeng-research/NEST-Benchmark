# Table 4 Fine-Tuning Experiments

This folder contains the paper-scoped fine-tuning materials for Table 4.
Training uses only Task 3 Generative Infilling on empty templates. The trained
adapters are then evaluated on the held-out Task 1, Task 2, and Task 3 test
splits.

Included data:

- `datasets/infill_both_template_train.jsonl`: Task 3 training split.
- `datasets/schema_both_template_test.jsonl`: Task 1 held-out evaluation split.
- `datasets/alignment_both_template_test.jsonl`: Task 2 held-out evaluation split.
- `datasets/infill_both_template_test.jsonl`: Task 3 held-out evaluation split.
- `llamafactory_data/magic_conch_fill_train.json`: LLaMA-Factory training data for `--dataset magic_conch`.
- `llamafactory_data/magic_conch_fill_test.json`: held-out Task 3 data in the same format.

The split is fixed at 80/20 with `--split_seed 3407` across both English and
Chinese templates.

## Build The Paper Data

Regenerate the package's paper-scoped datasets:

```bash
python -m finetune_experiments.build_finetune_dataset --task infill --split train --overwrite
python -m finetune_experiments.build_finetune_dataset --task all --split test --overwrite
python -m finetune_experiments.build_llamafactory_dataset --overwrite
```

`build_llamafactory_dataset` converts the Task 3 train/test JSONL files into
the `magic_conch_fill_{train,test}.json` format used by LLaMA-Factory.

## Fine-Tuning Command Used In The Experiments

The reported fine-tuning experiments were run with LLaMA-Factory. The command
was kept fixed across runs; only `--model_name_or_path` and `--output_dir`
changed for different base models and checkpoints.

```bash
llamafactory-cli train \
  --stage sft \
  --do_train True \
  --model_name_or_path /root/autodl-tmp/Models/Meta-Llama-3.1-8B-Instruct \
  --preprocessing_num_workers 16 \
  --finetuning_type lora \
  --template llama3 \
  --flash_attn auto \
  --dataset_dir data \
  --dataset magic_conch \
  --cutoff_len 4096 \
  --learning_rate 2e-05 \
  --num_train_epochs 3.0 \
  --max_samples 100000 \
  --per_device_train_batch_size 4 \
  --gradient_accumulation_steps 4 \
  --lr_scheduler_type cosine \
  --max_grad_norm 1.0 \
  --logging_steps 5 \
  --save_steps 100 \
  --warmup_steps 0 \
  --packing False \
  --enable_thinking True \
  --report_to none \
  --output_dir saves/Llama-3.1-8B-Instruct/lora/train_2026-05-24-03-21-42 \
  --bf16 True \
  --plot_loss True \
  --trust_remote_code True \
  --ddp_timeout 180000000 \
  --include_num_input_tokens_seen True \
  --optim adamw_torch \
  --lora_rank 8 \
  --lora_alpha 16 \
  --lora_dropout 0 \
  --lora_target all
```

## Evaluate Saved Checkpoint Predictions

Model checkpoints are not bundled. The package includes saved predictions and
Table 4 result files. To recompute Table 4 from those predictions:

```bash
python -m finetune_experiments.eval_existing_and_aggregate \
  --lang both \
  --schema_metric cpp
```

To generate predictions from a local checkpoint directory, use:

```bash
python -m finetune_experiments.predict_checkpoint \
  --checkpoint_dir /path/to/checkpoint \
  --lang both \
  --max_seq_length 32768 \
  --max_new_tokens 4096

python -m finetune_experiments.evaluate_checkpoint_predictions \
  --checkpoint_dir /path/to/checkpoint \
  --lang both \
  --schema_metric cpp
```

Predictions are saved under:

```text
finetune_experiments/predictions/{task}_empty/{lang}/finetuned_<model_name>/{sample_id}.json
```

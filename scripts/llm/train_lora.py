"""LoRA fine-tuning of the local report writer on data/llm/area-narrative/*.jsonl.

Run on a machine with an NVIDIA GPU (8 GB+ VRAM for Qwen2.5-1.5B) or a Colab GPU runtime,
NOT inside the project's Docker stack:

    python -m venv .venv-llm && .venv-llm\\Scripts\\activate      (Windows)
    pip install -r scripts/llm/requirements.txt
    python scripts/llm/train_lora.py --data data/llm/area-narrative --out scripts/llm/out

The loss is computed on the assistant answer only (the engine's facts are the input). The script
keeps the adapter, a merged full model, and a small held-out check. Converting to GGUF and
registering it in Ollama is described in scripts/llm/README.md. Training changes wording only:
the app still verifies every number and falls back to the template on any mismatch.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"  # same family as the Ollama default qwen2.5:1.5b


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode(tokenizer, messages: list[dict], max_len: int) -> dict | None:
    """input_ids for the whole chat; labels = -100 for system+user so only the answer is learned."""
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if len(full_ids) > max_len or full_ids[: len(prompt_ids)] != prompt_ids:
        return None
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return {"input_ids": full_ids, "attention_mask": [1] * len(full_ids), "labels": labels}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/llm/area-narrative")
    parser.add_argument("--out", default="scripts/llm/out")
    parser.add_argument("--base", default=BASE_MODEL)
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--min-keep", type=float, default=0.9,
                        help="stop when fewer than this share of training rows fit in --max-len (rows longer than it are dropped)")
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--accum", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="use only the first N training rows (smoke test)")
    parser.add_argument("--load-4bit", action="store_true", help="QLoRA: 4-bit base weights (bitsandbytes) for GPUs with 6 GB VRAM")
    parser.add_argument("--no-merge", action="store_true", help="save the adapter only")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq, Trainer, TrainingArguments

    random.seed(args.seed)
    data, out = Path(args.data), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    train_rows, eval_rows = read_jsonl(data / "train.jsonl"), read_jsonl(data / "eval.jsonl")
    if len(train_rows) < 50 and not args.limit:
        raise SystemExit(f"학습 예시가 {len(train_rows)}개뿐입니다. 과거 수집 후 llm-dataset을 다시 실행하세요.")

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if args.limit:
        train_rows = train_rows[: args.limit]
    train = [e for e in (encode(tokenizer, r["messages"], args.max_len) for r in train_rows) if e]
    held = [e for e in (encode(tokenizer, r["messages"], args.max_len) for r in eval_rows) if e]
    lengths = sorted(len(e["input_ids"]) for e in train)
    print(f"train {len(train)}/{len(train_rows)}  eval {len(held)}/{len(eval_rows)}  (dataset {manifest['created_at']})"
          + (f"  tokens min/median/max {lengths[0]}/{lengths[len(lengths) // 2]}/{lengths[-1]}" if lengths else ""))
    if len(train) < args.min_keep * len(train_rows):
        # 2026-10-05: 303 rows, only 135 fit in 2,048 tokens; training on the short ones silently skewed the model.
        raise SystemExit(f"--max-len {args.max_len} 안에 드는 학습 예시가 {len(train)}/{len(train_rows)}개뿐입니다. "
                         "--max-len을 늘리거나 근거 문장(area_report.NARRATIVE_FACTS)을 줄이세요.")

    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    if args.load_4bit:
        from peft import prepare_model_for_kbit_training
        from transformers import BitsAndBytesConfig
        model = AutoModelForCausalLM.from_pretrained(args.base, device_map={"": 0}, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if use_bf16 else torch.float16))
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16 if use_bf16 else torch.float16 if torch.cuda.is_available() else torch.float32)
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    if torch.cuda.is_available() and not use_bf16:
        # fp16 base weights (Turing/Pascal GPUs without bf16): the trainable LoRA weights must be fp32,
        # otherwise the fp16 grad scaler refuses to unscale them ("Attempting to unscale FP16 gradients").
        for parameter in model.parameters():
            if parameter.requires_grad:
                parameter.data = parameter.data.float()
    model.print_trainable_parameters()

    class AnswerOnlyTrainer(Trainer):
        """Cross-entropy only on the answer tokens, computing logits only there.

        The prompt (the engine's facts) is ~1,000 tokens and the answer ~250; asking the model for
        logits at every position costs 152k-vocab × prompt-length floats three times over (logits,
        softmax, gradient), which does not fit next to the base weights on a 6 GB card. With
        ``logits_to_keep`` the head runs only on the positions whose next token is a label."""

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop("labels")
            shifted = labels[:, 1:]
            keep = (shifted != -100).any(dim=0).nonzero(as_tuple=False).squeeze(-1)  # positions t whose target is token t+1
            outputs = model(**inputs, logits_to_keep=keep)
            logits = outputs.logits.float()
            targets = shifted[:, keep]
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1), ignore_index=-100)
            return (loss, outputs) if return_outputs else loss

    steps_per_epoch = math.ceil(len(train) / (args.batch * args.accum))
    trainer = AnswerOnlyTrainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(out / "checkpoints"), num_train_epochs=args.epochs, learning_rate=args.lr,
            per_device_train_batch_size=args.batch, per_device_eval_batch_size=args.batch, gradient_accumulation_steps=args.accum,
            lr_scheduler_type="cosine", warmup_ratio=0.05, logging_steps=max(1, steps_per_epoch // 5),
            eval_strategy="epoch", save_strategy="epoch", save_total_limit=1, load_best_model_at_end=True, prediction_loss_only=True,
            bf16=use_bf16, fp16=torch.cuda.is_available() and not use_bf16, seed=args.seed, report_to=[]),
        train_dataset=train, eval_dataset=held or None,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
    )
    trainer.train()
    final_eval = trainer.evaluate() if held else None
    adapter = out / "adapter"
    model.save_pretrained(adapter)
    tokenizer.save_pretrained(adapter)

    merged = out / "merged"
    if args.no_merge:
        merged = None
    elif args.load_4bit:
        # A 4-bit base cannot be merged in place: reload it in fp16 on the CPU and merge the adapter there.
        from peft import PeftModel
        del model
        torch.cuda.empty_cache()
        base = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.float16, low_cpu_mem_usage=True)
        PeftModel.from_pretrained(base, adapter).merge_and_unload().save_pretrained(merged, safe_serialization=True)
        tokenizer.save_pretrained(merged)
    else:
        model.merge_and_unload().save_pretrained(merged, safe_serialization=True)
        tokenizer.save_pretrained(merged)
    (out / "training.json").write_text(json.dumps({
        "base": args.base, "dataset_created_at": manifest["created_at"], "train": len(train), "eval": len(held),
        "epochs": args.epochs, "lr": args.lr, "rank": args.rank, "final_eval": final_eval, "load_4bit": args.load_4bit,
        "max_len": args.max_len, "limit": args.limit,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"adapter → {adapter}\nmerged  → {merged}\n다음 단계: scripts/llm/README.md 의 GGUF 변환·Ollama 등록·llm-eval")


if __name__ == "__main__":
    main()

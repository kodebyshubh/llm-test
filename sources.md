# Published figures, checked 2026-11-15 against the sources below

| Model | Licence (verified) | Params | Context | Headline published numbers | Source |
|---|---|---|---|---|---|
| Qwen3.5-4B | Apache 2.0 (HF tag) | ~4B (HF page shows 5B incl. vision) | 262,144 | MMLU-Pro 79.1, GPQA Diamond 76.2, IFEval 89.8, LiveCodeBench v6 55.8, all THINKING mode | https://huggingface.co/Qwen/Qwen3.5-4B |
| Qwen3.5-2B | Apache 2.0 | 2B | 262,144 | MMLU-Pro 66.5 thinking / 55.3 non-thinking; IFEval 78.6 thinking / 61.2 non-thinking | https://huggingface.co/Qwen/Qwen3.5-2B |
| Qwen3.5-0.8B | Apache 2.0 | 0.8B | 262,144 | MMLU-Pro 29.7 non-thinking / 42.3 thinking; IFEval 52.1 non-thinking / 44.0 thinking; GPQA 11.9 thinking | https://huggingface.co/Qwen/Qwen3.5-0.8B |
| Gemma 4 E2B | Apache 2.0 | 2.3B effective, 5.1B with embeddings | 128K | MMLU-Pro 60.0, GPQA Diamond 43.4; Q4_0 inference memory 2.9 GB (Google table) | https://huggingface.co/google/gemma-4-E2B-it ; https://ai.google.dev/gemma/docs/core |
| Phi-4-mini-instruct | MIT | 3.8B | 128K | MMLU 67.3, GSM8K 88.6, MATH 64.0 (HF card); HumanEval 74.4 (NVIDIA NIM model page, and Phi-4-Mini technical report) | https://huggingface.co/microsoft/Phi-4-mini-instruct ; https://docs.api.nvidia.com/nim/reference/microsoft-phi-4-mini-instruct ; https://arxiv.org/abs/2503.01743 |
| Granite 4.2 3B | Apache 2.0 | 3B | 128K (ext. 512K) | MMLU-Pro 67.84, AIME25 78.33, GPQA 54.80 | https://huggingface.co/ibm-granite/granite-4.2-3b |
| LFM3-1.7B | LFM Open License v1.0 (commercial use only below USD 10M annual revenue; non-commercial and research use allowed) | 1.73B | 256K | IFEval 96.66, GPQA Diamond 63.37, LiveCodeBench v6 73.46 | https://huggingface.co/LiquidAI/LFM3-1.7B ; https://huggingface.co/LiquidAI/LFM3-1.7B/blob/main/LICENSE |
| Nemotron 3 Nano 4B | NVIDIA Nemotron Open Model License | 3.97B | up to 262K | Reasoning on: AIME25 78.5, MATH500 95.4, GPQA 53.2; reasoning off: IFEval-Prompt 82.8. Card says supported language: English | https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16 |
| SmolLM3-3B | Apache 2.0 | 3B | 64K native, 128K with YaRN | IFEval 76.7 / GPQA Diamond 35.7 (no extended thinking); 71.2 / 41.7 (extended thinking) | https://huggingface.co/HuggingFaceTB/SmolLM3-3B |
| Llama 3.2 3B Instruct | Llama 3.2 Community License | 3.21B | 128K | MMLU 63.4, GSM8K (CoT) 77.7, IFEval 77.4 (bf16) | https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct |

Notes:
- Language: only Nemotron 3 Nano 4B is documented as English-only. Phi-4-mini, Granite 4.2, LFM3, SmolLM3 and Llama 3.2 list several languages on their HF pages; the Qwen3.5 and Gemma 4 models are multilingual. All are used in English here.
- Download sizes in the report are MEASURED (Ollama /api/tags size after pull), not the Ollama website figures.

## Calibration sources
- Intel N150 (GMKtec G3 Plus, 16 GB), CPU, llama3.2:3b via Ollama: 9.06 tokens/s. VERIFIED: https://github.com/geerlingguy/ai-benchmarks (README table) and https://github.com/geerlingguy/ai-benchmarks/issues/12
- Intel Core i5-10210U, Llama 3.2 3B Q4_K_M, about 10.0 tokens/s (MetriLLM): UNVERIFIED. A query of the MetriLLM leaderboard (https://metrillm.dev/) on 2026-11-15 found no i5-10210U / Llama 3.2 3B row. Shown only as a secondary, unverified reference.

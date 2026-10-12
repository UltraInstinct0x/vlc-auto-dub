"""Local translation with Meta's NLLB-200 (distilled 1.3B) via CTranslate2.

Much stronger than Argos for most pairs and translates any pair directly (no
English pivot). Runs on CPU (int8), fully offline after a one-time ~1.4 GB
model download from the Hugging Face Hub (OpenNMT's CTranslate2 conversion).

Model licence: CC-BY-NC 4.0 (non-commercial use).
"""
from __future__ import annotations

from ..errors import DependencyError, ProviderError

MODEL_REPO = "OpenNMT/nllb-200-distilled-1.3B-ct2-int8"
_FILES = ["model.bin", "config.json", "shared_vocabulary.json", "tokenizer.json",
          "special_tokens_map.json"]

# ISO 639-1 -> NLLB (FLORES-200) codes.
NLLB_CODES = {
    "ar": "arb_Arab", "bg": "bul_Cyrl", "ca": "cat_Latn", "cs": "ces_Latn",
    "da": "dan_Latn", "de": "deu_Latn", "el": "ell_Grek", "en": "eng_Latn",
    "es": "spa_Latn", "et": "est_Latn", "fa": "pes_Arab", "fi": "fin_Latn",
    "fr": "fra_Latn", "he": "heb_Hebr", "hi": "hin_Deva", "hr": "hrv_Latn",
    "hu": "hun_Latn", "id": "ind_Latn", "it": "ita_Latn", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "lt": "lit_Latn", "lv": "lvs_Latn", "nl": "nld_Latn",
    "no": "nob_Latn", "pl": "pol_Latn", "pt": "por_Latn", "ro": "ron_Latn",
    "ru": "rus_Cyrl", "sk": "slk_Latn", "sl": "slv_Latn", "sr": "srp_Cyrl",
    "sv": "swe_Latn", "th": "tha_Thai", "tr": "tur_Latn", "uk": "ukr_Cyrl",
    "vi": "vie_Latn", "zh": "zho_Hans",
}


def nllb_code(lang: str) -> str:
    code = NLLB_CODES.get(lang)
    if code is None:
        supported = ", ".join(sorted(NLLB_CODES))
        raise ProviderError(f"nllb: language {lang!r} is not mapped; supported: {supported}")
    return code


class NllbTranslator:
    def __init__(self, beam_size: int = 4):
        self.beam_size = beam_size
        self._translator = None
        self._tokenizer = None

    def _load(self):
        if self._translator is None:
            try:
                import ctranslate2
                from huggingface_hub import snapshot_download
                from tokenizers import Tokenizer
            except ImportError as exc:  # pragma: no cover
                raise DependencyError(
                    "provider 'nllb' needs ctranslate2, tokenizers and huggingface_hub "
                    "(installed with faster-whisper)"
                ) from exc
            try:
                path = snapshot_download(MODEL_REPO, allow_patterns=_FILES)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(f"nllb: could not download {MODEL_REPO}: {exc}") from exc
            self._translator = ctranslate2.Translator(path, device="cpu", compute_type="int8")
            self._tokenizer = Tokenizer.from_file(f"{path}/tokenizer.json")
        return self._translator, self._tokenizer

    def translate_batch(self, texts: list[str], source: str, target: str) -> list[str]:
        if source == target or not texts:
            return list(texts)
        src, tgt = nllb_code(source), nllb_code(target)
        translator, tok = self._load()
        batch = [
            [src] + tok.encode(t, add_special_tokens=False).tokens + ["</s>"]
            for t in texts
        ]
        try:
            results = translator.translate_batch(
                batch,
                target_prefix=[[tgt]] * len(batch),
                beam_size=self.beam_size,
                max_batch_size=16,
                repetition_penalty=1.1,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"nllb translation {source!r}->{target!r} failed: {exc}") from exc
        out = []
        for res in results:
            tokens = res.hypotheses[0]
            if tokens and tokens[0] == tgt:
                tokens = tokens[1:]
            ids = [tok.token_to_id(t) for t in tokens]
            text = tok.decode([i for i in ids if i is not None], skip_special_tokens=True)
            # NLLB learned subtitle dialogue dashes ("- Tamam."); drop them.
            out.append(text.strip().lstrip("-").strip())
        return out

    def translate(self, text: str, source: str, target: str) -> str:
        return self.translate_batch([text], source, target)[0]

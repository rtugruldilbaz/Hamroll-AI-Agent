from faster_whisper import WhisperModel

from config.app_settings import get_language


_model = None


def get_model():
    global _model

    if _model is None:
        print("[Voice] Loading Whisper model...")
        _model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8",
        )
        print("[Voice] Whisper model ready.")

    return _model


def transcribe_audio(
    file_path: str,
    language: str | None = None,
) -> str:
    language = language or get_language()

    if language not in {"tr", "en"}:
        language = "tr"

    segments, _ = get_model().transcribe(
        file_path,
        language=language,
        beam_size=5,
        temperature=0,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 400,
        },
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
    )

    return " ".join(
        segment.text.strip()
        for segment in segments
        if segment.text.strip()
    ).strip()
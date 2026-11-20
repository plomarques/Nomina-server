"""
Pre-launch check: for every language the app offers, show which Cloud TTS voice the server
picks and synthesize a short sample with it ("1 2 3", read by each voice in its own language).

Not a route: runs locally and is not part of the Cloud Run deploy.
Run with the same Google credentials as the server (e.g. `gcloud auth application-default login`):
    python check_tts_coverage.py            # list + synthesize samples into ./tts_samples/
    python check_tts_coverage.py --dry-run  # only list the choices, no synthesis
Respects TTS_VOICE_TIERS, like the server.
"""
import os
import sys

from google.cloud import texttospeech

import language_support as ls


def main(dry_run: bool) -> int:
    languages = ls.build_language_list("en")
    out_dir = "tts_samples"
    os.makedirs(out_dir, exist_ok=True)

    with_voice = [lang for lang in languages if lang["ttsSupported"]]
    failures = []
    print(f"Voice tiers: {', '.join(ls.VOICE_TIER_ORDER)}")
    print(f"{len(languages)} languages, {len(with_voice)} with pronunciation\n")

    for lang in languages:
        code = lang["languageCode"]
        locale, voice = ls.voice_for(code)
        status = "-"
        if voice and not dry_run:
            try:
                response = ls.tts_client().synthesize_speech(
                    input=texttospeech.SynthesisInput(text="1 2 3"),
                    voice=texttospeech.VoiceSelectionParams(language_code=locale, name=voice),
                    audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
                )
                with open(os.path.join(out_dir, f"{code}.mp3"), "wb") as f:
                    f.write(response.audio_content)
                status = "OK"
            except Exception as e:
                status = f"FAILED: {e}"
                failures.append(code)
        print(f"{code:10} {lang['translatedName']:32} {locale or '':8} {voice or '':30} {status}")

    if failures:
        print(f"\n{len(failures)} failures: {', '.join(failures)}")
        return 1
    if not dry_run:
        print(f"\nAll samples saved in ./{out_dir}/ - listen to a few of them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))

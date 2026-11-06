"""Медиа-команды шлюза: картинка, речь, видео — ответ типизирован (URL или файл), без разбора форматов.

Фейковый шлюз отдаёт записанные ответы; сеть подменена `gateway_cli` из conftest.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

IMAGE_MODEL = "openai/gpt-image-1"
IMAGE_URL = "https://img.test/cat.png"


def image_reply(**fields) -> dict:
    """Ответ `/images/generations`: URL картинки, модель и цена в usage.cost."""
    return {
        "created": 1750000000,
        "model": IMAGE_MODEL,
        "usage": {"cost": 0.04},
        "data": [{"url": IMAGE_URL}],
        **fields,
    }


def video_reply(**fields) -> dict:
    """Ответ `/videos/*`: id, состояние, ссылка на файл, модель и цена."""
    return {
        "id": "video_1",
        "status": "completed",
        "url": "https://video.test/1.mp4",
        "model": "google/veo-3",
        "usage": {"cost": 0.5},
        **fields,
    }


# --- картинки ---------------------------------------------------------------------


def test_image_generation_returns_the_url_model_and_cost(gateway_cli, gateway):
    fake = gateway(httpx.Response(200, json=image_reply()))
    result = gateway_cli(fake, "image", "generate", "кот в шляпе", "-m", IMAGE_MODEL)
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert body["url"] == IMAGE_URL
    assert body["model"] == IMAGE_MODEL
    assert body["cost"] == pytest.approx(0.04)
    assert str(fake.requests[0].url) == "http://gateway.test/v1/images/generations"
    assert fake.bodies()[0]["prompt"] == "кот в шляпе"
    assert fake.bodies()[0]["model"] == IMAGE_MODEL


def test_image_generation_writes_a_base64_answer_to_the_output_file(gateway_cli, gateway, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + "картинка".encode()
    reply = {**image_reply(), "data": [{"b64_json": base64.b64encode(png).decode()}]}
    out = tmp_path / "cat.png"
    result = gateway_cli(
        gateway(httpx.Response(200, json=reply)), "image", "generate", "кот", "-m", IMAGE_MODEL, "--out", str(out)
    )
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == png
    body = json.loads(result.stdout)
    assert body["path"] == str(out)
    assert body["model"] == IMAGE_MODEL


# --- речь -------------------------------------------------------------------------


def test_audio_speech_writes_the_bytes_and_reports_the_path(gateway_cli, gateway, tmp_path):
    fake = gateway(httpx.Response(200, content=b"ID3mp3bytes", headers={"content-type": "audio/mpeg"}))
    out = tmp_path / "speech.mp3"
    result = gateway_cli(
        fake, "audio", "speech", "привет", "-m", "openai/gpt-4o-mini-tts", "--voice", "alloy", "--out", str(out)
    )
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"ID3mp3bytes"
    body = json.loads(result.stdout)
    assert body["path"] == str(out)
    assert body["content_type"] == "audio/mpeg"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/audio/speech"
    assert fake.bodies()[0] == {
        "model": "openai/gpt-4o-mini-tts",
        "input": "привет",
        "voice": "alloy",
    }


def test_audio_transcription_returns_the_text(gateway_cli, gateway, tmp_path):
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"ID3audio")
    reply = {"text": "привет", "model": "openai/whisper-1", "usage": {"cost": 0.006}}
    fake = gateway(httpx.Response(200, json=reply))
    result = gateway_cli(fake, "audio", "transcribe", str(audio), "-m", "openai/whisper-1")
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["text"] == "привет"
    assert body["model"] == "openai/whisper-1"
    assert body["cost"] == pytest.approx(0.006)
    request = fake.requests[0]
    assert str(request.url) == "http://gateway.test/v1/audio/transcriptions"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="file"' in request.content and b"speech.mp3" in request.content and b"ID3audio" in request.content


def test_audio_voices_lists_the_gateway_voices(gateway_cli, gateway):
    reply = {"data": [{"id": "alloy", "name": "Alloy"}, {"id": "verse", "name": "Verse"}]}
    fake = gateway(httpx.Response(200, json=reply))
    result = gateway_cli(fake, "audio", "voices")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["voices"] == ["alloy", "verse"]
    assert fake.requests[0].method == "GET"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/audio/voices"


# --- видео ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "path"),
    [
        (("video", "generate", "волна", "-m", "google/veo-3"), "/videos/generations"),
        (("video", "edit", "https://video.test/1.mp4", "--prompt", "закат", "-m", "google/veo-3"), "/videos/edits"),
        (
            ("video", "extend", "https://video.test/1.mp4", "--prompt", "дальше", "-m", "google/veo-3"),
            "/videos/extensions",
        ),
    ],
    ids=["generate", "edit", "extend"],
)
def test_video_commands_return_the_job(gateway_cli, gateway, args, path):
    fake = gateway(httpx.Response(200, json=video_reply()))
    result = gateway_cli(fake, *args)
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert (body["id"], body["status"], body["url"]) == ("video_1", "completed", "https://video.test/1.mp4")
    assert body["model"] == "google/veo-3"
    assert body["cost"] == pytest.approx(0.5)
    assert str(fake.requests[0].url) == "http://gateway.test/v1" + path


def test_video_get_reads_the_job_by_id(gateway_cli, gateway):
    fake = gateway(httpx.Response(200, json=video_reply(status="processing", url=None)))
    result = gateway_cli(fake, "video", "get", "video_1")
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["status"] == "processing" and body["url"] is None
    assert fake.requests[0].method == "GET"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/videos/video_1"

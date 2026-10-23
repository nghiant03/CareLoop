"""PaddleOCR PP-StructureV3 in an isolated process with resumable page artifacts."""

import hashlib
import io
import json
import multiprocessing
import os
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory

from careloop.evidence.structure import PARSER_VERSION


def pipeline():
    root = Path(os.environ.get("CARELOOP_DATA_DIR", Path.home() / ".local/share/careloop"))
    for variable, folder in {
        "PADDLE_PDX_CACHE_HOME": "paddlex",
        "HF_HOME": "huggingface",
        "XDG_CACHE_HOME": "cache",
    }.items():
        os.environ.setdefault(variable, str(root / "models" / folder))
    try:
        import paddle
        from paddleocr import PPStructureV3
    except ImportError as exc:
        raise ValueError("Install ocr plus ocr-gpu/ocr-cpu extras, or rebuild Docker") from exc
    device = os.environ.get("CARELOOP_OCR_DEVICE", "cpu")
    if device not in {"cpu", "gpu:0"}:
        raise ValueError("CARELOOP_OCR_DEVICE must be cpu or gpu:0")
    if device.startswith("gpu") and (
        not paddle.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1
    ):
        raise ValueError("CUDA OCR requested but no GPU is available; check Docker GPU access")
    return PPStructureV3(
        device=device,
        # Paddle 3.3.1's oneDNN executor rejects layout-model PIR double-array attributes.
        enable_mkldnn=False,
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        use_table_recognition=True,
        use_formula_recognition=False,
        use_chart_recognition=False,
    )


def parse_pdf(payload, first=1, last=None, factory=pipeline):
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(payload))
    if reader.is_encrypted or len(reader.pages) > 500:
        raise ValueError("Encrypted PDF or document exceeds 500 pages")
    last = last or len(reader.pages)
    if not 1 <= first <= last <= len(reader.pages):
        raise ValueError("Page range falls outside the document")
    root = Path(os.environ.get("CARELOOP_DATA_DIR", Path.home() / ".local/share/careloop"))
    cache = root / "ocr" / PARSER_VERSION / hashlib.sha256(payload).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    engine, pages, empty = None, [], []
    with TemporaryDirectory(prefix="careloop-ocr-") as temporary:
        for number in range(first, last + 1):
            artifact = cache / f"{number}.json"
            if artifact.exists():
                page = json.loads(artifact.read_text())
            else:
                engine = engine if engine is not None else factory()
                writer = PdfWriter()
                writer.add_page(reader.pages[number - 1])
                path = Path(temporary) / "page.pdf"
                writer.write(path)
                results = list(engine.predict(input=str(path)))
                if len(results) != 1:
                    raise ValueError(f"PaddleOCR returned unexpected page count for page {number}")
                result = results[0].json
                if isinstance(result, str):
                    result = json.loads(result)
                parsed = result.get("res", result)
                blocks = parsed.get("parsing_res_list")
                if not isinstance(blocks, list):
                    raise ValueError("PaddleOCR output is missing layout blocks")
                page = {
                    "page": number,
                    "blocks": blocks,
                    "device": os.environ.get("CARELOOP_OCR_DEVICE", "cpu"),
                }
                # Atomic replace keeps a killed worker's partial output out of the cache.
                staging = artifact.with_suffix(f".{os.getpid()}.tmp")
                staging.write_text(json.dumps(page))
                staging.replace(artifact)
            if not any(b.get("block_content", "").strip() for b in page["blocks"]):
                empty.append(number)
            pages.append(page)
    return {
        "pages": pages,
        "empty_pages": empty,
        "total_pages": len(reader.pages),
        "selected_pages": [first, last],
        "parser": PARSER_VERSION,
    }


def _worker(sender, payload, first, last):
    try:
        sender.send((True, parse_pdf(payload, first, last)))
    except ValueError as exc:
        sender.send((False, str(exc)))
    except Exception as exc:
        sender.send(
            (False, f"PaddleOCR failed ({type(exc).__name__}); check OCR dependencies/models")
        )
    finally:
        sender.close()


def extract_pdf(payload, first=1, last=None):
    if os.environ.get("CARELOOP_OCR_DEVICE") == "gpu:0":
        # The linker reads this at process startup, before the spawned worker imports Paddle.
        libraries = sorted((Path(sysconfig.get_paths()["purelib"]) / "nvidia").glob("*/lib"))
        previous = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(
            dict.fromkeys([*(str(path) for path in libraries), *previous.split(":")])
        ).strip(":")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, payload, first, last))
    try:
        process.start()
        sender.close()
        if not receiver.poll(float(os.environ.get("CARELOOP_OCR_TIMEOUT", "7200"))):
            raise ValueError("PaddleOCR timed out; completed pages are cached for restart")
        try:
            success, result = receiver.recv()
        except EOFError as exc:
            raise ValueError(
                "PaddleOCR worker exited before completing; check memory/model availability"
            ) from exc
        if not success:
            raise ValueError(result)
        return result
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()

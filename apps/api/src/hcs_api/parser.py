from __future__ import annotations

from pathlib import Path

from .models import ImageBlock, SourceMaterial, SourcePage, TextBlock


def parse_source(file_path: Path, project_root: Path, original_filename: str) -> SourceMaterial:
    suffix = file_path.suffix.lower()
    if suffix == ".pptx":
        return parse_pptx(file_path, project_root, original_filename)
    if suffix == ".pdf":
        return parse_pdf(file_path, original_filename)
    raise ValueError("Only PPTX and PDF files are supported in v0.1")


def parse_pptx(file_path: Path, project_root: Path, original_filename: str) -> SourceMaterial:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(str(file_path))
    pages: list[SourcePage] = []
    image_dir = project_root / "assets" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    for slide_index, slide in enumerate(presentation.slides, start=1):
        title = ""
        text_blocks: list[TextBlock] = []
        images: list[ImageBlock] = []

        if slide.shapes.title and getattr(slide.shapes.title, "text", "").strip():
            title = slide.shapes.title.text.strip()

        image_count = 0
        for shape_index, shape in enumerate(slide.shapes, start=1):
            if getattr(shape, "has_text_frame", False):
                text = "\n".join(
                    paragraph.text.strip()
                    for paragraph in shape.text_frame.paragraphs
                    if paragraph.text.strip()
                ).strip()
                if text:
                    kind = "title" if not title or text == title else "body"
                    if not title:
                        title = text.splitlines()[0]
                    text_blocks.append(
                        TextBlock(
                            id=f"p{slide_index}_t{shape_index}",
                            text=text,
                            kind=kind,
                            left=_emu_to_points(getattr(shape, "left", None)),
                            top=_emu_to_points(getattr(shape, "top", None)),
                            width=_emu_to_points(getattr(shape, "width", None)),
                            height=_emu_to_points(getattr(shape, "height", None)),
                        )
                    )

            if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE and hasattr(shape, "image"):
                image_count += 1
                image = shape.image
                ext = image.ext or "png"
                filename = f"source_p{slide_index}_{image_count}.{ext}"
                output_path = image_dir / filename
                output_path.write_bytes(image.blob)
                images.append(
                    ImageBlock(
                        id=f"source_p{slide_index}_{image_count}",
                        path=f"assets/images/{filename}",
                        filename=filename,
                        width=_emu_to_points(getattr(shape, "width", None)),
                        height=_emu_to_points(getattr(shape, "height", None)),
                    )
                )

        pages.append(
            SourcePage(
                page_number=slide_index,
                title=title or f"第 {slide_index} 页",
                text_blocks=text_blocks,
                images=images,
            )
        )

    return SourceMaterial(source_type="pptx", original_filename=original_filename, pages=pages)


def parse_pdf(file_path: Path, original_filename: str) -> SourceMaterial:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError("PyMuPDF is required for PDF parsing") from exc

    document = fitz.open(file_path)
    pages: list[SourcePage] = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0] if lines else f"PDF 第 {index} 页"
        pages.append(
            SourcePage(
                page_number=index,
                title=title,
                text_blocks=[
                    TextBlock(id=f"p{index}_t1", text=text, kind="body")
                ]
                if text
                else [],
                ocr_text="" if text else "OCR pending: scanned PDF support is experimental in v0.1.",
            )
        )
    return SourceMaterial(source_type="pdf", original_filename=original_filename, pages=pages)


def _emu_to_points(value: object) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 12700, 2)
    except (TypeError, ValueError):
        return None


"""Test data factories for HanClassStudio tests."""

from hcs_api.models import SourceMaterial, SourcePage, TextBlock, ImageBlock, LessonProfile


def _make_greeting_source() -> SourceMaterial:
    """Create a source material that looks like a greeting lesson."""
    return SourceMaterial(
        source_type="pptx",
        original_filename="第1课_您好.pptx",
        pages=[
            SourcePage(
                page_number=1,
                title="第1课 您好",
                text_blocks=[
                    TextBlock(id="p1_t1", text="Nín hǎo - Hello", kind="body"),
                    TextBlock(id="p1_t2", text="你好 (nǐ hǎo) - Hello", kind="body"),
                    TextBlock(id="p1_t3", text="您好 (nín hǎo) - Hello (polite)", kind="body"),
                    TextBlock(id="p1_t4", text="你们好 (nǐmen hǎo) - Hello (plural)", kind="body"),
                    TextBlock(id="p1_t5", text="再见 (zài jiàn) - Goodbye", kind="body"),
                ],
            ),
            SourcePage(
                page_number=2,
                title="对话",
                text_blocks=[
                    TextBlock(id="p2_t1", text="A：你好！", kind="body"),
                    TextBlock(id="p2_t2", text="B：你好！", kind="body"),
                    TextBlock(id="p2_t3", text="A：您好，老师！", kind="body"),
                    TextBlock(id="p2_t4", text="B：你们好！", kind="body"),
                ],
            ),
            SourcePage(
                page_number=3,
                title="问候",
                text_blocks=[
                    TextBlock(id="p3_t1", text="跟你的同学说一说：你好！", kind="body"),
                    TextBlock(id="p3_t2", text="跟老师说：您好！", kind="body"),
                ],
            ),
        ],
    )


def _make_zaine_source() -> SourceMaterial:
    """Create a source with 在...呢 pattern for grammar detection."""
    return SourceMaterial(
        source_type="pptx",
        original_filename="第14课_我在学习中文呢.pptx",
        pages=[
            SourcePage(
                page_number=1,
                title="第14课 我在学习中文呢",
                text_blocks=[
                    TextBlock(id="p1_t1", text="我在学习中文呢。", kind="body"),
                    TextBlock(id="p1_t2", text="A：你在做什么？", kind="body"),
                    TextBlock(id="p1_t3", text="B：我在学习中文呢。", kind="body"),
                    TextBlock(id="p1_t4", text="你在看书吗？", kind="body"),
                ],
            ),
        ],
    )


def _make_stroke_noise_source() -> SourceMaterial:
    """Create a source that contains stroke words and basic vocab."""
    return SourceMaterial(
        source_type="pptx",
        original_filename="笔画练习.pptx",
        pages=[
            SourcePage(
                page_number=1,
                title="笔画",
                text_blocks=[
                    TextBlock(id="p1_t1", text="横 竖 撇 捺", kind="body"),
                    TextBlock(id="p1_t2", text="一 二 三", kind="body"),
                    TextBlock(id="p1_t3", text="笔画名称：横、竖、撇、捺", kind="body"),
                    TextBlock(id="p1_t4", text="学习写汉字", kind="body"),
                ],
            ),
        ],
    )

from hcs_api.typography import resolve_typography, validate_pinyin
from hcs_api.renderer import render_lesson
from hcs_api.models import LessonProfile, LessonBlueprint, AssetManifest, QualityReport

def test_scripts_and_roles_cover_supported_languages():
 for locale,script in [("en-US","Latn"),("fr-FR","Latn"),("ja-JP","Jpan"),("ko-KR","Kore"),("ar-SA","Arab"),("zh-TW","Hant")]:
  p=resolve_typography("zh-CN",locale)
  assert p.roles["explanation"].script==script
 assert resolve_typography("zh-CN","ar-SA").roles["explanation"].direction=="rtl"
def test_requested_font_and_pinyin_validation():
 p=resolve_typography(requested={"target_text":"PingFang SC","explanation":"Missing"})
 assert p.roles["target_text"].resolved_font=="PingFang SC"
 assert p.roles["explanation"].warnings
 assert all(validate_pinyin(x) for x in ["nǐ","nǚ","lüè","zǎoshang","lǎoshī"])
def test_html_propagates_rtl(tmp_path):
 h=render_lesson(tmp_path,LessonProfile(explanation_language="ar-SA"),LessonBlueprint(),AssetManifest(),QualityReport())
 assert 'dir="rtl"' in h.read_text()

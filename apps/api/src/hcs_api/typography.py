"""Locale/script-aware font resolution; themes retain only visual hierarchy."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

SCRIPT_BY_TAG = {"zh-CN":"Hans", "zh-SG":"Hans", "zh-TW":"Hant", "zh-HK":"Hant", "ja-JP":"Jpan", "ko-KR":"Kore", "ar-SA":"Arab"}
FALLBACKS = {
 "Hans":["Microsoft YaHei","PingFang SC","Noto Sans CJK SC"], "Hant":["Microsoft JhengHei","PingFang TC","Noto Sans CJK TC"],
 "Jpan":["Yu Gothic","Hiragino Sans","Noto Sans CJK JP"], "Kore":["Malgun Gothic","Apple SD Gothic Neo","Noto Sans CJK KR"],
 "Arab":["Noto Sans Arabic","Arial","Geeza Pro"], "Latn":["Aptos","Arial","Source Sans 3","Noto Sans"],
}

class TypographyRole(BaseModel):
 model_config=ConfigDict(extra="forbid")
 role:str; locale:str; script:str; direction:str; requested_font:str|None=None; resolved_font:str; fallback_chain:list[str]=Field(default_factory=list); reason:str=""; warnings:list[str]=Field(default_factory=list)
class TypographyProfile(BaseModel):
 model_config=ConfigDict(extra="forbid")
 target_language:str; explanation_language:str; transliteration_system:str; interface_language:str; roles:dict[str,TypographyRole]

def script_for(locale:str)->str:
 return SCRIPT_BY_TAG.get(locale, "Arab" if locale.split("-")[0]=="ar" else "Latn")
def direction_for(script:str)->str: return "rtl" if script=="Arab" else "ltr"
def resolve_typography(target_language="zh-CN", explanation_language="en-US", transliteration_system="pinyin", interface_language="zh-CN", requested:dict|None=None)->TypographyProfile:
 requested=requested or {}
 def role(name,locale,script=None):
  script=script or script_for(locale); chain=FALLBACKS[script]; want=requested.get(name); chosen=want if want in chain else chain[0]
  return TypographyRole(role=name,locale=locale,script=script,direction=direction_for(script),requested_font=want,resolved_font=chosen,fallback_chain=chain,reason="teacher_selected" if want in chain else "script_fallback",warnings=[] if not want or want in chain else [f"Requested font '{want}' unavailable for {script}; used {chosen}."])
 return TypographyProfile(target_language=target_language,explanation_language=explanation_language,transliteration_system=transliteration_system,interface_language=interface_language,roles={"display_title":role("display_title",target_language),"target_text":role("target_text",target_language),"transliteration":role("transliteration","en-US","Latn"),"explanation":role("explanation",explanation_language),"instructions_ui":role("instructions_ui",interface_language),"numeric_symbol":role("numeric_symbol","en-US","Latn")})

def validate_pinyin(text:str)->bool:
 return all(ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZǐǚèǎīáéóúǘǜńňǹü " for ch in text)

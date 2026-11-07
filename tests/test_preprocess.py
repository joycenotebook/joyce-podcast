from scripts.pipeline.numbers import convert_numbers, int_to_zh
from scripts.pipeline.preprocess import filler_hits, preprocess


def test_quantities_and_years():
    assert int_to_zh(10) == "十"
    assert int_to_zh(14) == "十四"
    assert int_to_zh(25) == "二十五"
    assert int_to_zh(101) == "一百零一"
    assert int_to_zh(190) == "一百九十"
    assert int_to_zh(200) == "两百"
    assert int_to_zh(400) == "四百"
    assert int_to_zh(2000) == "两千"
    assert int_to_zh(2800) == "两千八百"
    assert int_to_zh(10001) == "一万零一"
    assert int_to_zh(20000) == "两万"
    assert int_to_zh(2) == "二"
    assert convert_numbers("2026年收入做到190亿美元，不是2026个苹果。") == "二零二六年收入做到一百九十亿美元，不是两千零二十六个苹果。"
    assert convert_numbers("400亿和2800万") == "四百亿和两千八百万"
    assert convert_numbers("14个月，$1美元，$1 美元，25%。") == "十四个月，一美元，一美元，百分之二十五。"
    assert "美元美元" not in convert_numbers("$1美元")
    assert convert_numbers("2.5亿") == "二点五亿"


def test_english_paragraph_is_not_renumbered():
    result = preprocess("大家好，欢迎回来，发声。\n这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。\n\nIn 2026 revenue hit $190 billion.\n\n如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。\n")
    english = [s.text for s in result.segments if s.lang == "en"]
    assert english == ["In 2026 revenue hit $190 billion."]


def test_skips_non_spoken_sections_and_cleans_fillers():
    md = """
# 标题

## 审核附件

这里有 2026 和 like，但不出声。

## 课程导读

大家好，欢迎回来，发声。
这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。

今天是 2026 年，规模 400亿。别读成「发声」。

## 英文原文与讲解

先把结论说完。

### 产能

十年后骑手会更多。

Um, you know, I was like, we feel like this is the constraint.

中文收束。$1美元 不要叠读。

## 生词表

| word | IPA |
| like | laɪk |

如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。
"""
    result = preprocess(md, title="产能")
    spoken = result.spoken_text
    assert "审核附件" not in spoken
    assert "laɪk" not in spoken
    assert "生词" not in spoken
    assert "别读成" not in spoken
    assert "二零二六" in spoken
    assert "四百亿" in spoken
    assert "一美元" in spoken
    assert result.unattached_headings == []
    assert "英文原文与讲解" in spoken
    assert "产能" in spoken
    english = next(s.text for s in result.segments if s.lang == "en")
    assert filler_hits(english) == []
    assert "feel like" in english
    assert "I said" in english or "i said" in english.lower()


def test_unattached_heading_is_reported():
    md = """
大家好，欢迎回来，发声。
这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。

### 只有英文

Yeah, this heading has no Chinese carrier.

如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。
"""
    result = preprocess(md)
    assert result.unattached_headings == ["只有英文"]

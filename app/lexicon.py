"""禁用詞、書面轉換、法例提示。提示不是法律意見，也不引用具體大廈公契條號。"""

from __future__ import annotations

import re

SOURCE_DECLARATION = "僅根據提供資料轉寫，不含推測。"
UNKNOWN = "未有記錄"
DISCLAIMER = (
    "本文件是草稿。AI 只整理保安口述，最終由當值保安或主管確認簽署。"
    "系統不提供法律意見，不判斷法律責任，不把事件定性為犯罪或違約。"
)

# 改寫表處理不到、仍然不能入事實的主觀詞。態度、搞事、醉漢由 auto_rewrite 刪或改寫，不再追問。
BANNED = (
    "可疑",
    "故意",
    "滋事",
    "懷疑",
    "小偷",
    "賊人",
    "意圖",
    "唔合作",
    "不合作",
    "不懷好意",
    "心術不正",
    "一定係",
    "一定是",
    "明顯係",
    "明顯是",
    "無賴",
    "惡霸",
)

# 口述出現醉或酒時，嚴謹版用這句，不再把「醉酒」當主觀禁用詞。
DRUNK_PHRASE = "一名疑似醉酒之男子"
_DRUNK_MENTION = re.compile(r"醉漢|醉酒|喝醉|飲酒|酒味|酗酒|醉咗|醉了|飲醉")
_DRUNK_REWRITE = (
    re.compile(r"(?:一名|一個|一位)?醉漢"),
    re.compile(r"疑似醉酒(?:之)?(?:男子|男人|漢)?"),
    re.compile(r"(?<!疑似)(?:一名|一個|一位)?醉酒(?:之)?(?:男子|男人|漢)?"),
    re.compile(r"喝醉(?:的|嘅)?(?:男人|男子|漢)?"),
    re.compile(r"飲酒(?:的|嘅)?(?:男人|男子|漢)?"),
    re.compile(r"飲醉(?:的|嘅)?(?:男人|男子|漢)?"),
    re.compile(r"酗酒(?:的|嘅)?(?:男人|男子|漢)?"),
)
_DRUNK_KEEP = "\ue000"

_WRITTEN = (
    ("佢哋", "他們"),
    ("佢", "對方"),
    ("睇到", "看到"),
    ("見到", "看到"),
    ("呢個", "這個"),
    ("嗰個", "那個"),
    ("嘅", "的"),
    ("咗", "了"),
    ("喺", "在"),
    ("冇", "沒有"),
    ("唔", "不"),
    ("嚟", "來"),
    ("啲", "些"),
)

EVENT_LABELS = {
    "facility_damage": "設施損壞",
    "noise": "違規噪音",
    "fall_injury": "現場跌倒受傷",
    "parking": "違泊",
    "unknown": "未能分類",
    "out_of_scope": "本期不處理",
}

MVP_EVENTS = ("facility_damage", "noise", "fall_injury")

_BASE_HINTS = {
    "facility_damage": (
        "可人手翻查：大廈公契關於公用部分維修、滲水或設施保養的條款。"
        "本系統不自動引用任何大廈的條號，請主管按該廈公契文本填寫。",
        "可人手翻查：佔用人法律責任條例（香港法例第314章）是否與地面濕滑或設施故障有關。"
        "本系統不判斷法律責任。",
    ),
    "noise": (
        "可人手翻查：噪音管制條例（香港法例第400章）。本系統不判斷是否構成違例。",
        "大廈公契：不自動對應。請主管按該廈公契關於滋擾、住用的條款人手填寫。",
    ),
    "fall_injury": (
        "可人手翻查：佔用人法律責任條例（香港法例第314章）。本系統不判斷法律責任。",
        "大廈公契：不自動對應。請主管按該廈公契關於公用部分保養的條款人手填寫。",
    ),
}

_EXTRA_HINTS = (
    ("煙", "可人手翻查：吸煙（公眾衞生）條例（香港法例第371章）。本系統不判斷是否違法。"),
    (
        ("揮拳", "揮手", "揮左", "揮右", "掌摑", "推倒", "打人"),
        "可人手翻查：普通襲擊，《侵害人身罪條例》（香港法例第212章）。"
        "此句只因口述出現推撞或揮手等動作而列出，不是案件定性。",
    ),
)

DMC_LINE = "大廈公契：未作自動對應。主管按該廈文本填寫適用條款：____________________"


def has_banned(text: str) -> list[str]:
    if not text:
        return []
    return [word for word in BANNED if word in text]


_DELETE_PHRASES = (
    "態度很差",
    "態度好差",
    "態度惡劣",
    "態度差",
    "令人驚恐",
    "唔講道理",
    "好差",
    "惡劣",
    "囂張",
    "無禮",
    "好驚",
    "好煩",
    "搞事",
    "嘈交",
    "麻煩",
)
_LEAD = re.compile(r"^(?:補充|時間改為|地點改為|傷勢改為|日期改為)\s*[:：]?\s*")
_EMPTY_BODY = re.compile(r"[對方他她佢的了呢啊呀\s，,。：:]+")


_ASR_FIXES = (
    ("天花敵人", "天花滴水"),
    ("好百萬聲", "砰砰聲"),
    ("百萬聲", "砰砰聲"),
    ("女用戶用女住戶", "一名女住戶"),
    ("女用戶用", "女住戶"),
    ("女用戶", "女住戶"),
    ("好善", "濕滑"),
)


def asr_normalize(text: str | None) -> str:
    """語音錯字先過表，再抽欄。不把錯字寫進事實。"""
    if not text:
        return ""
    normalized = text
    for src, dst in _ASR_FIXES:
        normalized = normalized.replace(src, dst)
    return normalized


def auto_rewrite(text: str | None) -> str:
    """規則表改寫。評價詞刪走，不追問；醉漢改成疑似醉酒。不估時間地點。"""
    if not text:
        return ""
    text = asr_normalize(text)
    female = bool(re.search(r"女|女士|女人|婆婆|女童", text)) and "醉漢" not in text
    person = "一名疑似醉酒之女子" if female else DRUNK_PHRASE
    protected = text.replace(DRUNK_PHRASE, _DRUNK_KEEP)
    protected = re.sub(r"(?:有個|有一名|一名|一個|一位)?醉漢", DRUNK_PHRASE, protected)
    protected = re.sub(r"(?:有個|有一名|一名|一個|一位)?酒鬼", person, protected)
    for src, dst in (
        ("攞住酒飲", "手持酒類飲品飲用"),
        ("好醉", "表現疑似醉酒"),
        ("醉到", "表現疑似醉酒"),
        ("醉咗", "表現疑似醉酒"),
        ("醉了", "表現疑似醉酒"),
        ("飲酒", "手持酒類飲品飲用"),
        ("好大聲", "大聲"),
        ("應該係", "據報"),
        ("應該是", "據報"),
        ("估計係", "據報"),
        ("估計是", "據報"),
        ("可能係", "據報"),
        ("可能是", "據報"),
        ("癮君子", ""),
        ("飛仔", ""),
    ):
        protected = protected.replace(src, dst)
    if "多次" not in protected:
        protected = protected.replace("成日", "").replace("經常", "")
    protected = re.sub(r"(?<![據報稱])係住戶", "據稱住戶", protected)
    for phrase in _DELETE_PHRASES:
        protected = protected.replace(phrase, "")
    protected = protected.replace(_DRUNK_KEEP, DRUNK_PHRASE)
    kept = []
    for chunk in re.split(r"[。！？!?；;\n]+", protected):
        for part in re.split(r"[，,]", chunk):
            clause = part.strip(" ，,。")
            body = _EMPTY_BODY.sub("", _LEAD.sub("", clause))
            if clause and body:
                kept.append(clause)
    return "，".join(kept)


def mentions_drunk(text: str) -> bool:
    return bool(text and _DRUNK_MENTION.search(text))


def rewrite_drunk(text: str | None) -> str | None:
    if not text or not mentions_drunk(text):
        return text
    protected = text.replace(DRUNK_PHRASE, _DRUNK_KEEP)
    for pattern in _DRUNK_REWRITE:
        protected = pattern.sub(DRUNK_PHRASE, protected)
    rewritten = protected.replace(_DRUNK_KEEP, DRUNK_PHRASE)
    return re.sub(rf"(?:{re.escape(DRUNK_PHRASE)}){{2,}}", DRUNK_PHRASE, rewritten)


def to_written(text: str) -> str:
    if not text:
        return text
    converted = text
    for src, dst in _WRITTEN:
        converted = converted.replace(src, dst)
    if has_banned(converted) and not has_banned(text):
        return text
    return converted


def legal_hints(event_type: str, corpus: str) -> list[str]:
    hints = list(_BASE_HINTS.get(event_type, ()))
    for needle, line in _EXTRA_HINTS:
        keys = needle if isinstance(needle, tuple) else (needle,)
        if any(key in corpus for key in keys):
            hints.append(line)
    if not any("大廈公契" in item for item in hints):
        hints.append("大廈公契：不自動對應。請主管按該廈文本人手填寫。")
    hints.append("以上全部是參考提示，不是法律意見，不是案件定性。")
    return hints

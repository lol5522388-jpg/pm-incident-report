"""從口述抽出欄位。只抄原文片段，不補情節。"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.asr_normalize import normalize_asr
from app.date_patterns import parse_date_text
from app.lexicon import DRUNK_PHRASE, UNKNOWN, auto_rewrite, has_banned, mentions_drunk, rewrite_drunk
from app.negation_policy import fall_asserted, injury_status_phrase

_WIDTH = {ord("　"): " "}
for _code in range(0xFF01, 0xFF5E + 1):
    _WIDTH[_code] = chr(_code - 0xFEE0)

_TAKEN = re.compile(
    r"已經|我已|通知|致電|召喚|放置告示|拉住|貼出|貼告示|報警|報案|對講機|拍照|影相|影咗|上前詢問|勸喻"
)
_WITNESS = re.compile(r"見到|看到|睇到|聽到|聽見|聽得到|見不到|目擊|^我由|^我喺|^我在")
_INJURY_NONE = re.compile(
    r"沒有人受傷|無人受傷|無受傷|未見有人受傷|未見受傷|沒有受傷|"
    r"冇人跌倒|沒有人跌倒|未有人跌倒|未有.*跌倒|未見.*跌倒"
)
_INJURY_POS = re.compile(r"有血|流血|紅腫|瘀|痛|清醒|行唔到|走唔到")
_ABSENCE = re.compile(r"現場沒有其他人|沒有其他人|無其他人|未見其他人|電梯內無人|現場沒有人")
_PARTY = re.compile(r"(?:一名|一個|一位|有一名).{0,36}?(?:男子|女士|男性|女性|男人|女人|伯伯|婆婆|男童|女童|小童)")
_HM = re.compile(r"(?<!\d)(?P<h>\d{1,2})\s*[:：時]\s*(?P<m>\d{1,2})\s*分?")
_CN_TIME = re.compile(
    r"(?P<part>凌晨|早上|上午|中午|下午|晚上|夜晚|夜裡)?"
    r"(?P<h>[零〇一二三四五六七八九十兩\d]{1,3})\s*點"
    r"(?P<m>半|幾|許多|幾多|[零〇一二三四五六七八九十\d]{1,3}\s*分?)?"
)
_VAGUE = re.compile(r"頭先|啱啱|剛才|大概|大約|差唔多|差不多|點幾|幾點|早排")
_ROUGH_TIME = re.compile(r"左右|大概|大約|差唔多|差不多")
_EXPLICIT_DATE = re.compile(r"(?P<y>\d{4})\s*年\s*(?P<mo>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日號号]")
_SPOT = "消防樓梯|後樓梯|電梯大堂|電梯|垃圾房|接待處|梯間|走廊|大堂|車位|門口|通道|樓梯|天台|平台|困梯"
_FLOOR = r"地庫\s*[A-Za-z]?\s*\d{0,2}|地下|(?<!\d)\d{1,2}樓|[一二三四五六七八九十兩]{1,3}樓"
_LOC = re.compile(
    rf"(?:[\u4e00-\u9fff]{{2,8}}(?:閣|苑|園|軒|居|大廈|中心))?"
    rf"[A-Za-z]座(?:{_FLOOR})[^，。；\n]{{0,18}}?(?:{_SPOT})(?:對出|近電梯門|門外)?"
)
_LOC_ESTATE = re.compile(
    rf"(?!樓)[\u4e00-\u9fff]{{2,8}}邨[\u4e00-\u9fff]{{2,8}}樓(?:{_FLOOR})(?:[^，。；\n]{{0,4}})?(?:{_SPOT})"
)
_UNCERTAIN_FLOOR = re.compile(
    r"\d{1,2}\s*定\s*\d{1,2}|"
    r"[十兩一二三四五六七八九十]{1,4}\s*定\s*[十兩一二三四五六七八九十]{1,4}|"
    r"唔敢講|不敢講|唔敢講死|不敢講死"
)
_COLLOQUIAL = re.compile(r"呀|啦|㗎|喇|囉|餵|嗰|依家|咁樣|喺度")
_NAME = re.compile(
    r"(?<![主])[\u4e00-\u9fff]Sir"
    r"|(?<![主])[\u4e00-\u9fff]{1,2}(?:先生|小姐|太太)"
    r"|(?<![發產醫男女學先主])[\u4e00-\u9fff]生(?!活)"
    r"|(?<![主])[\u4e00-\u9fff]太(?!太)"
)
_SKIP_NAMES = {"先生", "學生", "醫生", "男生", "女生", "產生", "發生"}

_ACTION = {
    "facility_damage": re.compile(r"漏水|水滴|水漬|滴水|滴到|滲水|好濕|爆喉|水浸|無法打開|故障|晾衫"),
    "noise": re.compile(r"唱歌|卡拉OK|大聲|喧嘩|好嘈|拍門|關上房門|站在門口"),
    "fall_injury": re.compile(r"跌倒|摔倒|跌親|摔低|著地|撐地|坐在地上|向前跌"),
    "parking": re.compile(r"違泊|霸住車位|霸位|車牌|車位"),
}
_OBSERVED = re.compile(r"推倒|跌倒|摔倒|叫喊|大聲|揮拳|揮手|打人|坐在|坐於|打開")


def fold_width(text: str) -> str:
    return text.translate(_WIDTH)


def split_clauses(text: str) -> list[str]:
    clauses = []
    beats = re.split(r"[。！？!?；;\n]+|(?=咁我)|(?=但係)|(?=但我)|(?=所以)|(?=我做咗)|(?=我做嘅)", text)
    for chunk in beats:
        for part in re.split(r"[，,]", chunk):
            part = part.strip()
            if part:
                clauses.append(part)
    return clauses


def classify(text: str) -> str:
    noisy = re.search(r"唱歌|卡拉OK|喧嘩|噪音|嘈音|拍門|大聲|好嘈|砰砰|鬧交|鬧", text)
    watery = re.search(
        r"漏水|水浸|爆喉|水滴|水漬|滴水|滲水|污水|溢流|垃圾房|無法打開|壞電梯|電梯門|地滑|好滑|濕滑",
        text,
    )
    if fall_asserted(text):
        return "fall_injury"
    # 又嘈又有水時，主線是喧嘩，不把走廊有水改成設施損壞。
    if noisy:
        return "noise"
    if watery:
        return "facility_damage"
    if re.search(r"違泊|違例泊|霸住車位|霸位|車牌", text):
        return "parking"
    return "unknown"


def _cn_number(token: str | None) -> int | None:
    if token is None:
        return 0
    token = token.strip().replace("分", "")
    if not token:
        return 0
    if token.isdigit():
        return int(token)
    if token == "半":
        return 30
    if token == "幾":
        return None
    table = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if token == "十":
        return 10
    if "十" in token:
        left, _, right = token.partition("十")
        tens = table.get(left, 1) if left else 1
        ones = table.get(right, 0) if right else 0
        if left and left not in table:
            return None
        if right and right not in table:
            return None
        return tens * 10 + ones
    return table.get(token)


def _apply_daypart(hour: int, part: str | None) -> int:
    if part in {"下午", "晚上", "夜晚", "夜裡"} and 1 <= hour <= 11:
        return hour + 12
    if part in {"晚上", "夜晚", "夜裡"} and hour == 12:
        return 0
    if part in {"凌晨", "早上", "上午"} and hour == 12:
        return 0
    return hour


# 明確「N點M分」、無時段：1–6 點口語多指下午；7–11 點多指上午（八點二十→08:20，三點四十→15:40）
_CN_EXPLICIT_MINUTE_PM_HOURS = range(1, 7)


def _pm_guess_for_cn_explicit(hour: int, part: str | None) -> bool:
    if part in {"凌晨", "早上", "上午"}:
        return False
    if part in {"下午", "晚上", "夜晚", "夜裡", "中午"}:
        return True
    if part:
        return False
    return hour in _CN_EXPLICIT_MINUTE_PM_HOURS


def explicit_minute_pm_rule_count() -> int:
    return len(tuple(_CN_EXPLICIT_MINUTE_PM_HOURS))


def _hour24_from_cn(hour: int, part: str | None, *, allow_pm_guess: bool = True) -> tuple[int, bool]:
    """口語「三點四十」多指下午；無時段且 1–11 點 → 可推斷 PM（標約／待確認）。"""
    if part in {"凌晨", "早上", "上午"}:
        return (_apply_daypart(hour, part), False)
    if part in {"下午", "晚上", "夜晚", "夜裡", "中午"}:
        return (_apply_daypart(hour, part), False)
    if hour == 12:
        return (12, False)
    if allow_pm_guess and 1 <= hour <= 11:
        return (hour + 12, True)
    return (hour, False)


_RANGE = re.compile(
    r"由\s*(?P<h1>\d{1,2})\s*[:：點]\s*(?P<m1>\d{1,2})\s*分?\s*至\s*(?P<h2>\d{1,2})\s*[:：點]\s*(?P<m2>\d{1,2})"
)
_APPROX = re.compile(r"約\s*(?P<h>\d{1,2})\s*[:：點]\s*(?P<m>\d{1,2})")


def _stamp(hour: int, minute: int) -> str | None:
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def clocks(text: str) -> list[str]:
    """按出現次序收集精確鐘點。『十一點幾』不會變成一個鐘點。"""
    found: list[str] = []
    for match in _HM.finditer(text or ""):
        stamp = _stamp(int(match.group("h")), int(match.group("m")))
        if stamp and stamp not in found:
            found.append(stamp)
    for match in _CN_TIME.finditer(text or ""):
        hour = _cn_number(match.group("h"))
        minute_token = match.group("m")
        minute = _cn_number(minute_token) if minute_token else 0
        if hour is None or minute is None:
            continue
        hour = _apply_daypart(hour, match.group("part"))
        stamp = _stamp(hour, minute)
        if stamp and stamp not in found:
            found.append(stamp)
    return found


def _clock(text: str) -> dict:
    span = _RANGE.search(text)
    if span:
        start = _stamp(int(span.group("h1")), int(span.group("m1")))
        end = _stamp(int(span.group("h2")), int(span.group("m2")))
        if start and end:
            return {"value": f"由 {start} 至 {end}", "status": "confirmed", "vague": False}
    approx = _APPROX.search(text)
    if approx:
        stamp = _stamp(int(approx.group("h")), int(approx.group("m")))
        if stamp:
            return {"value": f"約 {stamp}", "status": "confirmed", "vague": False}
    vague = _VAGUE.search(text) is not None
    match = _HM.search(text)
    if match:
        hour, minute = int(match.group("h")), int(match.group("m"))
        if hour <= 23 and minute <= 59:
            value = f"{hour:02d}:{minute:02d}"
            return {"value": value, "status": "needs_confirm" if vague else "confirmed", "vague": vague}
    cn = _CN_TIME.search(text)
    if cn:
        hour = _cn_number(cn.group("h"))
        minute_token = cn.group("m")
        if minute_token in {None, "幾", "許多", "幾多"}:
            if hour is not None and 0 <= hour <= 23:
                hour, _pm = _hour24_from_cn(hour, cn.group("part"), allow_pm_guess=False)
                return {
                    "value": f"約 {hour:02d}:00",
                    "status": "needs_confirm",
                    "vague": True,
                }
            return {"value": None, "status": "missing", "vague": True}
        minute = _cn_number(minute_token) if minute_token else 0
        if hour is None or minute is None or not (0 <= hour <= 23 and 0 <= minute <= 59):
            return {"value": None, "status": "missing", "vague": True}
        explicit_cn_minute = minute_token not in {None, "幾", "許多", "幾多", "半"}
        if explicit_cn_minute:
            allow_pm_guess = _pm_guess_for_cn_explicit(hour, cn.group("part"))
        else:
            allow_pm = bool(cn.group("part")) and cn.group("part") not in {"凌晨", "早上", "上午"}
            allow_pm_guess = allow_pm
        hour, pm_guess = _hour24_from_cn(
            hour, cn.group("part"), allow_pm_guess=allow_pm_guess
        )
        stamp = f"{hour:02d}:{minute:02d}"
        window = text[max(0, cn.start() - 3) : cn.end() + 6]
        rough = _ROUGH_TIME.search(text) is not None or re.search(r"約", window)
        if explicit_cn_minute:
            prefix = "約 " if (rough or pm_guess) else ""
            return {"value": f"{prefix}{stamp}".strip(), "status": "confirmed", "vague": bool(rough or pm_guess)}
        if rough or pm_guess:
            return {"value": f"約 {stamp}", "status": "needs_confirm", "vague": True}
        return {"value": stamp, "status": "confirmed", "vague": False}
    return {"value": None, "status": "missing", "vague": vague}


def _day(text: str, today: date) -> dict:
    parsed = parse_date_text(text, today)
    if parsed:
        return {
            "value": parsed.label_zh,
            "status": "confirmed",
            "iso": parsed.iso,
            "pattern": parsed.pattern,
        }
    return {"value": None, "status": "missing"}


def _location_match(text: str) -> str | None:
    found = [item.group(0) for item in _LOC.finditer(text)]
    found.extend(item.group(0) for item in _LOC_ESTATE.finditer(text))
    found.extend(re.findall(r"[A-Za-z]座\s*地下", text))
    found = [item for item in found if not item.startswith("樓")]
    if not found:
        return None
    return max(found, key=len)


def apply_written_facts(fields: dict, text: str) -> None:
    """把模板書面句寫入欄位，避免目擊事實誤判缺漏。"""
    seen, done, injury = _written_lines(text)
    if seen and not (fields.get("action") or {}).get("value"):
        fields["action"] = _field(seen)
    if done and not (fields.get("action_taken") or {}).get("value"):
        fields["action_taken"] = _field(done)
    if injury and not (fields.get("injury") or {}).get("value"):
        fields["injury"] = _field(injury)


def _location(text: str) -> dict:
    if _UNCERTAIN_FLOOR.search(text):
        return {"value": None, "status": "missing", "origin": "auto"}
    found = _location_match(text)
    if not found:
        return {"value": None, "status": "missing", "origin": "auto"}
    return {"value": found, "status": "confirmed", "origin": "auto"}


def specific_location(text: str) -> str | None:
    return _location_match(fold_width(text))


def _is_taken(clause: str) -> bool:
    if re.match(r"^(對方|該名|男子|女士|住戶|佢)", clause):
        return False
    return _TAKEN.search(clause) is not None


def _join(clauses: list[str], pred) -> str | None:
    picked = [clause for clause in clauses if pred(clause)]
    if not picked:
        return None
    return "，".join(picked)


def _action_text(text: str, pattern: re.Pattern[str] | None) -> str | None:
    """保留動作句及其後的補充，剔走主觀詞、已採取行動和句首的時間。"""
    if pattern is None:
        return None
    kept: list[str] = []
    for sentence in re.split(r"[。！？!?；;\n]+|(?=咁我)|(?=但係)|(?=但我)|(?=所以)|(?=我做咗)|(?=我做嘅)", text):
        clauses = [part.strip() for part in re.split(r"[，,]", sentence) if part.strip()]
        if not any(pattern.search(clause) and not has_banned(clause) for clause in clauses):
            continue
        started = False
        for clause in clauses:
            if has_banned(clause) or _is_taken(clause):
                continue
            if pattern.search(clause):
                started = True
                kept.append(clause)
            elif started:
                kept.append(clause)
    if not kept:
        return None
    return "，".join(kept)


def _names(text: str) -> list[dict]:
    found = []
    seen = set()
    for match in _NAME.finditer(text):
        name = match.group(0)
        if name in _SKIP_NAMES or name in seen:
            continue
        seen.add(name)
        found.append({"value": name, "status": "pending"})
    return found


def _subjective(text: str) -> list[dict]:
    hits = []
    for word in has_banned(text):
        hits.append({"word": word, "status": "pending", "observed": None})
    return hits


def _add_line(bucket: list[str], line: str) -> None:
    if line not in bucket:
        bucket.append(line)


def _written_lines(text: str) -> tuple[str | None, str | None, str | None]:
    """只產出短書面句。對不上就留空，不把口語原句當事實。"""
    seen: list[str] = []
    done: list[str] = []
    injury = None
    if re.search(r"晾衫", text):
        _add_line(seen, "有人在樓梯晾衫")
    if "推倒" in text:
        _add_line(seen, "有人推倒椅子" if "椅" in text else "有人推倒物件")
    if re.search(r"滴水|滴到", text) and "天花滴水" not in text:
        _add_line(seen, "現場有滴水")
    if "砰砰" in text:
        _add_line(seen, "單位門發出砰砰聲")
    if re.search(r"大聲|喧嘩|鬧|嘈音|嘈", text):
        _add_line(seen, "有人大聲喧嘩")
    if re.search(r"抽煙|吸煙|食煙", text):
        _add_line(seen, "有人在公眾地方抽煙")
    if "煙灰" in text:
        _add_line(seen, "現場有煙灰")
    if re.search(r"污水|溢流", text):
        _add_line(seen, "見垃圾房外走廊地面有污水溢流")
    if re.search(r"住戶通知|有住戶通知|住戶報|有住戶報", text):
        _add_line(seen, "有住戶向管理處報告")
    if re.search(r"困梯|報困", text):
        _add_line(seen, "有住戶報告困梯")
    if "酒味" in text:
        _add_line(seen, "一名男子帶有酒味，站在門口")
    if re.search(r"灘水", text) or ("走廊" in text and "水" in text):
        _add_line(seen, "走廊地面有水")
    if "濕滑" in text or re.search(r"好滑|地滑", text):
        _add_line(seen, "地面濕滑")
    if "天花滴水" in text and re.search(r"未見|沒有見|無見", text):
        _add_line(seen, "未見天花滴水")
    elif "天花滴水" in text:
        _add_line(seen, "天花有滴水")
    if "晾衫" in text and "勸喻" in text:
        _add_line(done, "保安勸喻住客不要晾衫，並將衣物移開")
    elif "勸喻" in text:
        _add_line(done, "保安表明身份，勸喻雙方降低聲量")
    if re.search(r"通知控制室|通知了控制室|通知咗控制室|叫控制室", text):
        _add_line(done, "已通知控制室")
    if re.search(r"對講", text) and "控制室" in text:
        _add_line(done, "已以對講通知控制室")
    if re.search(r"對講", text) and re.search(r"陳\s*Sir|主管", text):
        _add_line(done, "已用對講通知當值主管陳Sir到場")
    if re.search(r"告示牌|貼出告示|放置告示", text):
        _add_line(done, "已放置告示牌")
    if re.search(r"升降機公司|召升降機", text):
        _add_line(done, "已通知控制室召升降機公司")
    if re.search(r"對講", text) and re.search(r"清潔|維修", text):
        _add_line(done, "已以對講通知管理處安排清潔及維修")
    elif re.search(r"清潔|維修", text):
        _add_line(done, "已通知管理處安排清潔及維修")
    if re.search(r"清潔完成|已清潔|清好", text):
        _add_line(done, "清潔已完成")
    if "閉路" in text:
        _add_line(done, "已安排翻查閉路電視")
    neg_injury = injury_status_phrase(text)
    if neg_injury:
        injury = neg_injury
    elif re.search(r"沒有人受傷|冇人受傷|無人受傷|未見有人受傷", text):
        injury = "未見有人受傷"
    if re.search(r"沒有入過單位|冇入過單位|無入過單位|沒有進入單位", text):
        _add_line(done, "保安沒有進入單位")
    if re.search(r"未入垃圾房|冇入垃圾房|沒有進入垃圾房|無入垃圾房", text):
        _add_line(done, "保安沒有進入垃圾房")
    elif re.search(r"污水|垃圾房", text) and re.search(r"未入|冇入|沒有入|無入", text):
        _add_line(done, "保安沒有進入垃圾房")
    if re.search(r"閂門|入返個單位|返回單位", text):
        _add_line(done, "在場人士返回單位並關門")
    if re.search(r"入電梯|進電梯|入咗電梯", text):
        _add_line(done, "該男子進入電梯離開")
    return (
        "。".join(seen) or None,
        "。".join(done) or None,
        injury,
    )


def _keep_short(value: str | None) -> str | None:
    if not value or _COLLOQUIAL.search(value):
        return None
    return value


def _field(value: str | None, status: str | None = None) -> dict:
    if value:
        return {"value": value, "status": status or "confirmed", "origin": "auto"}
    return {"value": None, "status": "missing", "origin": "auto"}


def extract(text: str, *, today: date) -> dict:
    raw = normalize_asr(fold_width(text)).strip()
    text = auto_rewrite(raw)
    event = classify(raw)
    clauses = split_clauses(text)
    action_re = _ACTION.get(event) or _OBSERVED

    def is_injury(clause: str) -> bool:
        return _INJURY_NONE.search(clause) is not None or _INJURY_POS.search(clause) is not None

    def is_witness(clause: str) -> bool:
        return not _is_taken(clause) and _WITNESS.search(clause) is not None

    party = _ABSENCE.search(text)
    party_value = party.group(0) if party else None
    if party_value is None:
        described = _PARTY.search(text)
        party_value = described.group(0) if described else None
    action_value = _action_text(text, action_re)
    if mentions_drunk(text):
        party_value = rewrite_drunk(party_value)
        action_value = rewrite_drunk(action_value)
        absent = party_value and _ABSENCE.fullmatch(party_value)
        if not absent and (not party_value or DRUNK_PHRASE not in party_value):
            party_value = f"{party_value}，{DRUNK_PHRASE}" if party_value else DRUNK_PHRASE

    clock = _clock(text)
    day = _day(text, today)
    date_field = _field(day["value"], day["status"] if day["value"] else "missing")
    if day.get("iso"):
        date_field["iso"] = day["iso"]
    seen, done, injury_line = _written_lines(text)
    raw_action = _keep_short(action_value)
    raw_taken = _keep_short(_join(clauses, _is_taken))
    action_value = seen if seen and (not raw_action or "我" in raw_action) else raw_action
    taken_value = done if done and (not raw_taken or "我" in raw_taken) else raw_taken
    witness_value = _keep_short(_join(clauses, is_witness))
    neg_phrase = injury_status_phrase(text)
    if neg_phrase:
        injury_value = neg_phrase
    else:
        injury_value = _keep_short(_join(clauses, is_injury)) or injury_line
    return {
        "event_type": event,
        "fields": {
            "date": date_field,
            "time": _field(clock["value"], clock["status"] if clock["value"] else "missing"),
            "location": _location(text),
            "party": _field(party_value),
            "action": _field(action_value),
            "witness": _field(witness_value),
            "injury": _field(injury_value),
            "action_taken": _field(taken_value),
        },
        "names": _names(text),
        "subjective": _subjective(text),
        "transcript": raw,
    }


def blank_case_fields() -> dict:
    return {key: _field(None) for key in ("date", "time", "location", "party", "action", "witness", "injury", "action_taken")}


def display_value(field: dict) -> str:
    if field.get("status") == "unknown":
        return UNKNOWN
    return field.get("value") or UNKNOWN

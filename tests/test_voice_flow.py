import re
from datetime import date, datetime, timedelta, timezone

from app.pipeline import Pipeline
from app.store import Store
from app.voice_flow import hear
from tests.voice_helpers import hear_report

STAMP = datetime(2026, 10, 22, 18, 0, tzinfo=timezone(timedelta(hours=8)))
ELEVATOR = (
    "今日09:05，A座2樓電梯大堂，2號電梯門無法打開，電梯內無人。"
    "我在大堂見到電梯門關閉。沒有人受傷。我已經通知主管。"
)


def make_pipe(tmp_path) -> Pipeline:
    return Pipeline(Store(tmp_path / "cases.db"), today=date(2026, 10, 22), now=STAMP, engine="heuristic")


def test_gaps_are_spoken_and_not_filled_into_a_complete_report(tmp_path):
    pipe = make_pipe(tmp_path)
    view = hear(pipe, "guard-1", "昨晚大概10點幾，A座後樓梯有個醉漢搞事，推倒椅子，態度很差")
    assert view["complete"] is False
    assert "時間或時段" in view["gaps"]
    assert "日期" in view["gaps"]
    assert "地點" not in view["gaps"]
    assert "仍缺" in view["say"] or "仍欠" in view["say"]
    assert "1." in view["say"]
    assert "來源聲明" not in view["say"]
    assert "收到" in view["say"]
    assert "推倒" in "".join(view["check"]["right"])
    assert view["document"] is None
    assert "態度很差" not in view["say"]
    assert "搞事" not in "".join(view["check"]["right"])
    assert "醉漢" not in view["say"]
    blocked = hear(pipe, "guard-1", "傳送")
    assert blocked["sent"] is False
    assert "未送畀主管" in blocked["say"]


def test_complete_report_delivers_formal_and_summary_in_say(tmp_path):
    pipe = make_pipe(tmp_path)
    view = hear_report(pipe, "guard-2", ELEVATOR)
    assert view["complete"] is True
    assert view["gaps"] == []
    assert view["event_label"] == "設施損壞"
    assert view["document"]["kind"] == "report"
    assert "【物管事件報告" in view["say"]
    assert "（2）摘要版" in view["say"]
    assert "電梯" in view["say"]
    assert "【核對稿】" not in view["say"]
    assert any("電梯" in item for item in view["check"]["right"])


def test_voice_send_goes_to_supervisor_and_correction_is_applied(tmp_path):
    pipe = make_pipe(tmp_path)
    hear_report(pipe, "guard-3", ELEVATOR)
    changed = hear_report(pipe, "guard-3", "時間改為09:12")
    assert changed["complete"] is True
    stored = pipe.store.get(changed["case_id"])
    assert stored["fields"]["time"]["value"] == "09:12"
    sent = hear(pipe, "guard-3", "傳送")
    assert sent["sent"] is True
    assert sent["say"] == "已送畀主管。"
    assert list((tmp_path / "outbox").glob("*.eml"))


def test_spoken_estate_date_with_hao_is_not_reported_as_missing(tmp_path):
    pipe = make_pipe(tmp_path)
    spoken = (
        "10樓啟業邨啟悅樓一樓樓梯有用戶投訴有滴水，有人喺度晾衫。"
        "日期係2006年10月22號9點15分。咁我到場已經係9點17分。我見到有人晾衫。"
        "我做咗行動就係勸喻住客唔好晾衫。"
    )
    view = hear(pipe, "guard-drip", spoken)
    assert "日期" in view["gaps"]
    assert "2006" not in view["say"]
    assert view["document"] is None
    assert "地點" not in view["gaps"]
    assert "客觀事實" not in view["gaps"]
    assert "啟悅樓" in "".join(view["check"]["right"])
    assert "樓啟業邨" not in "".join(view["check"]["right"])
    corrected = hear(pipe, "guard-drip", "日期係2026年10月20號")
    assert "日期" not in corrected["gaps"]
    assert any(item.startswith("日期：2026年10月20日") for item in corrected["check"]["right"])


DRIP = (
    "餵餵而家個問題就係喺喺嗰個10樓啟業邨啟悅樓一樓樓梯有一個有一個用戶投訴有滴水嘅問題有人喺度晾衫"
    "日期係2006年10月22號9點15分咁我到場嘅時候係就已經係9點17分呀我見到我接到投訴之後去見到就見到有人喺嗰度晾衫嘅"
    "但係嗰人唔知係邊個嚟㗎我做咗行動就係勸喻嗰個住客就唔好晾衫但我搵唔到邊個住客其實所以我做嘅嘢都係收埋搬搬開"
)
PATROL = (
    "控制室我係大堂嗰個保安呀巡邏嗰個呀我依家我睇手錶先十一點幾b座我由第一行上去行到中斷就好大聲啦人喺度鬧"
    "咁道門好百萬聲咁響我行緊都要十幾樓15定16我唔敢講啦地下有灘水好善然之後裏住企喺門口只要對面單位都儲大聲"
    "與好差對面個男人有啲酒味企喺門口咁樣喺度鬧交啦咁我就表明身份叫即係勸喻雙方啦細聲啲唔好影響其他用戶啦"
    "咁然之後女用戶用女住戶就嘈多幾句鬧鬧到幾句之後呢都聽㗎喇都返去閂門㗎喇男呢亦都入返個單位嗰度㗎喇"
    "然之後我就檢查咗走廊啦咁水就唔知邊度嚟嘅未見天花敵人咁我啱啱通知咗控制室㗎喇就安排清潔同埋翻查閉路電視"
    "咁暫時就冇人受傷我都冇入過單位"
)


def test_judge_transcript_asks_before_pdf_and_splits_incidents(tmp_path):
    pipe = make_pipe(tmp_path)
    drip = hear(pipe, "guard-judge", DRIP)
    assert drip["complete"] is False
    assert drip["document"] is None
    assert "2006" not in drip["say"]
    assert "日期" in drip["gaps"]
    dated = hear_report(pipe, "guard-judge", "日期係2026年10月20號")
    assert dated["complete"] is True
    assert dated["case_id"] == drip["case_id"]
    formal = pipe.store.get(dated["case_id"])["report"]["formal"]
    summary = pipe.store.get(dated["case_id"])["report"]["summary"]
    assert "2026-10-20" in formal
    assert "啟業邨啟悅樓一樓樓梯" in formal
    assert "2006" not in formal
    assert "啟業邨啟悅樓一樓樓梯" in formal
    assert "有人在樓梯晾衫" in formal
    assert "現場有滴水" in formal
    assert "控制室我係" not in formal
    assert "餵" not in formal
    assert "來源聲明" not in formal
    assert "大廈公契" not in formal
    assert formal.count("僅根據提供資料客觀轉寫，不含推測。") == 1
    assert "09:15" in formal
    assert len([line for line in summary.splitlines() if re.match(r"\d+\. ", line)]) <= 5
    patrol = hear(pipe, "guard-judge", "新事件 " + PATROL)
    assert patrol["case_id"] != drip["case_id"]
    assert patrol["complete"] is False
    assert patrol["document"] is None
    assert patrol["event_label"] == "違規噪音"
    assert "時間或時段" in patrol["gaps"]
    assert "仍缺" in patrol["say"] or "仍欠" in patrol["say"]
    assert "樓層（口述未能確定）" in patrol["gaps"]
    assert "單位" not in " ".join(patrol["gaps"])
    blob = patrol["say"] + "".join(patrol["check"]["right"])
    assert "啟悅樓" not in blob
    assert "2006" not in blob
    assert "天花敵人" not in blob
    assert "百萬" not in blob
    assert "砰砰" in blob or "女住戶" in blob or "天花滴水" in blob or "濕滑" in blob


def test_same_period_is_one_block_and_different_times_stay_apart(tmp_path):
    pipe = make_pipe(tmp_path)
    span = hear_report(
        pipe,
        "guard-span",
        "今日由22:30至22:40，B座15樓走廊，有人大聲喧嘩。我到場勸喻。我通知控制室。沒有人受傷。",
    )
    assert span["complete"] is True
    formal = pipe.store.get(span["case_id"])["report"]["formal"]
    assert "22:30" in formal and "22:40" in formal
    split = hear_report(
        pipe,
        "guard-split",
        "今日22:30，B座15樓走廊聽到嘈音。22:35我到場勸喻。22:40通知控制室安排清潔同翻查閉路。沒有人受傷。",
    )
    assert split["complete"] is True
    split_formal = pipe.store.get(split["case_id"])["report"]["formal"]
    assert "22:30" in split_formal
    assert "（1）嚴謹版" in split_formal
    assert "勸喻" in split_formal or "控制室" in split_formal
    vague = hear(pipe, "guard-vague", "十一點幾之後B座走廊好大聲，我到場勸喻，通知控制室。15樓。沒有人受傷。")
    assert vague["complete"] is False
    assert "時間或時段" in vague["gaps"]
    assert vague["document"] is None


def test_event_types_are_not_limited_to_the_sample_reports(tmp_path):
    pipe = make_pipe(tmp_path)
    parking = hear_report(
        pipe,
        "guard-4",
        "今日10:15，A座地下車位，車牌AB1234霸住車位。我在場見到。我已經通知主管。",
    )
    assert parking["complete"] is True
    assert parking["event_label"] == "違泊"
    assert parking["status"] == "ready"
    other = hear_report(
        pipe,
        "guard-5",
        "今日11:20，B座3樓走廊，有人推倒椅子。我見到。我已經通知主管。",
    )
    assert other["event_label"] == "口述事件"
    assert other["complete"] is True
    assert other["status"] != "out_of_scope"

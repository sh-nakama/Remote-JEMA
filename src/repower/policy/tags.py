"""Topic tags for the policy observer: the vocabulary, and the rules that apply it.

A tag says what a committee (or one of its meetings) is *about* — 洋上風力, 系統用蓄電池,
系統接続 — so the Deep Dive can be sliced by topic instead of only by committee. The
first pass covers renewable generation, storage & flexibility, grid infrastructure,
the renewable support schemes, and a small group of other low-carbon sources.

Everything here is pure: no network, no database. Persistence lives in
:mod:`repower.policy.tagging`, which applies these rules to the DB.

Two separate questions are answered separately:

- **Committee tags** are its *standing mandate*. Curated in
  :mod:`repower.policy.committees` where we are sure, otherwise derived from the
  committee's name plus the topics its own meetings give enough *coverage* (see `coverage`).
- **Meeting tags** are what *that meeting* discussed. They deliberately do **not**
  inherit from the committee: a broad committee holding an offshore-wind-only meeting
  should surface under 洋上風力 alone, not under every topic it ever touches.

Matching is on Japanese keywords (committee and meeting text is Japanese). A tag may
carry *weak* keywords — generic words such as 太陽光 or 風力 — that count only when no
more specific sibling tag (``defer_to``) matched, so an offshore-wind meeting is not
also filed under onshore wind merely because it says 風力.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Tag:
    """One entry of the closed vocabulary."""

    key: str
    group: str
    ja: str
    en: str
    # What the LLM is told the tag means (also documents the rule keywords).
    desc: str
    keywords: tuple[str, ...] = ()
    # Generic words: only count when none of the ``defer_to`` tags matched.
    weak_keywords: tuple[str, ...] = ()
    defer_to: tuple[str, ...] = ()


@dataclass(frozen=True)
class Group:
    key: str
    ja: str
    en: str


GROUPS: tuple[Group, ...] = (
    Group("generation", "発電", "Generation"),
    Group("storage", "蓄電・調整力", "Storage & flexibility"),
    Group("grid", "系統設備", "Grid infrastructure"),
    Group("support", "支援制度", "Support schemes"),
    Group("lowcarbon", "その他の脱炭素電源", "Other low-carbon"),
)

# A keyword starting with ``re:`` is a regular expression; a pure-ASCII keyword is
# matched case-insensitively on word boundaries (so ``DR`` does not match inside
# ``ADR``); anything else is a plain substring.
TAGS: tuple[Tag, ...] = (
    # ── 発電 ────────────────────────────────────────────────────────────────
    Tag("solar_utility", "generation", "事業用太陽光", "Grid-scale solar",
        "Utility-scale / ground-mounted solar PV (事業用・大規模・地上設置の太陽光).",
        keywords=("事業用太陽光", "大規模太陽光", "メガソーラー", "地上設置", "野立て"),
        weak_keywords=("太陽光",), defer_to=("solar_rooftop", "solar_nextgen")),
    Tag("solar_rooftop", "generation", "屋根置き・住宅用太陽光", "Rooftop / distributed solar",
        "Rooftop, residential and building-mounted solar PV (屋根置き・住宅用).",
        keywords=("屋根置き", "屋根設置", "屋根上", "住宅用太陽光", "住宅屋根")),
    Tag("solar_nextgen", "generation", "次世代太陽電池", "Perovskite / next-gen PV",
        "Perovskite and other next-generation solar cells (ペロブスカイト・フィルム型).",
        keywords=("ペロブスカイト", "次世代太陽電池", "薄型太陽電池", "フィルム型太陽電池")),
    Tag("wind_offshore", "generation", "洋上風力", "Offshore wind",
        "Offshore wind: fixed-bottom and floating, promotion zones, the Offshore Wind Act (洋上風力).",
        keywords=("洋上風力", "洋上風車", "洋上風発", "着床式", "浮体式", "海域利用法",
                  "再エネ海域", "一般海域")),
    Tag("wind_onshore", "generation", "陸上風力", "Onshore wind",
        "Onshore / land-based wind power (陸上風力).",
        keywords=("陸上風力", "陸上風車"),
        weak_keywords=("風力発電", "風力"), defer_to=("wind_offshore",)),
    Tag("hydro_geothermal", "generation", "水力・地熱", "Hydro & geothermal",
        "Hydropower (incl. small / existing hydro) and geothermal generation.",
        keywords=("水力発電", "小水力", "中小水力", "既設水力", "地熱")),
    Tag("biomass", "generation", "バイオマス", "Biomass",
        "Biomass and wood-pellet power generation (バイオマス発電・木質).",
        keywords=("バイオマス", "木質ペレット", "木質チップ")),
    # ── 蓄電・調整力 ─────────────────────────────────────────────────────────
    Tag("storage_grid", "storage", "系統用蓄電池", "Grid-scale batteries",
        "Grid-connected / stand-alone battery energy storage (系統用蓄電池・BESS).",
        keywords=("系統用蓄電池", "蓄電池", "蓄電所", "蓄電システム", "電力貯蔵", "BESS", "定置用蓄電")),
    Tag("storage_pumped", "storage", "揚水・長期貯蔵", "Pumped hydro / long-duration storage",
        "Pumped-storage hydro and long-duration energy storage (揚水発電・長周期).",
        keywords=("揚水", "長期エネルギー貯蔵", "長期貯蔵", "長周期", "圧縮空気", "フロー電池")),
    Tag("der_vpp", "storage", "分散リソース・VPP・DR", "DER, VPP & demand response",
        "Distributed energy resources, virtual power plants, aggregators and demand response.",
        keywords=("VPP", "バーチャルパワープラント", "アグリゲーター", "ディマンドリスポンス",
                  "デマンドレスポンス", "DR", "分散型エネルギー", "分散型電源",
                  "分散エネルギーリソース", "DER")),
    # ── 系統設備 ────────────────────────────────────────────────────────────
    Tag("grid_planning", "grid", "広域系統整備・直流送電", "Grid master plan & HVDC",
        "Transmission planning and reinforcement: master plan, wide-area grid build-out, HVDC.",
        keywords=("広域系統", "マスタープラン", "直流送電", "HVDC", "系統増強", "系統整備",
                  "基幹系統", "送電線", "送電網", "次世代電力ネットワーク", "地内系統",
                  "系統設備", "系統インフラ")),
    Tag("grid_connection", "grid", "系統接続・ノンファーム", "Grid access & non-firm connection",
        "Connecting generation to the grid: connection rules, non-firm access, grid code.",
        keywords=("系統接続", "系統連系", "ノンファーム", "接続検討", "接続契約", "系統アクセス",
                  "空き容量", "連系協議", "グリッドコード", "電源接続案件募集", "接続申込")),
    Tag("grid_curtailment", "grid", "出力制御・混雑管理", "Curtailment & congestion",
        "Output curtailment of renewables, congestion management and redispatch.",
        keywords=("出力制御", "出力抑制", "混雑管理", "系統混雑", "混雑処理", "リディスパッチ", "再給電")),
    Tag("grid_cost", "grid", "託送料金・費用負担", "Network charges & cost allocation",
        "Network tariffs and who pays for grid investment: 託送料金, 発電側課金, revenue cap.",
        keywords=("託送", "発電側課金", "レベニューキャップ", "一般負担", "特定負担", "系統利用料")),
    Tag("grid_distribution", "grid", "配電・レジリエンス", "Distribution & resilience",
        "Distribution networks, distribution licensing and grid resilience.",
        # 送配電 (transmission-and-distribution) is in nearly every grid document, so a
        # bare 配電 must not count.
        keywords=("re:(?<!送)配電(事業|系統|網|設備|線|ネットワーク|ライセンス)", "無電柱化", "電柱")),
    # ── 支援制度 ────────────────────────────────────────────────────────────
    Tag("support_fit_fip", "support", "FIT/FIP・調達価格", "FIT/FIP & procurement prices",
        "Feed-in tariff / feed-in premium schemes, procurement price calculation, the levy.",
        keywords=("FIT", "FIP", "固定価格買取", "調達価格", "基準価格", "賦課金", "調達期間")),
    Tag("support_ltda", "support", "長期脱炭素電源オークション", "Long-term decarbonisation auction",
        "The Long-Term Decarbonisation Power Source Auction (長期脱炭素電源オークション).",
        keywords=("長期脱炭素電源", "長期脱炭素", "脱炭素電源オークション", "LTDA")),
    # ── その他の脱炭素電源 ───────────────────────────────────────────────────
    Tag("hydrogen_ammonia", "lowcarbon", "水素・アンモニア", "Hydrogen & ammonia",
        "Hydrogen and ammonia as power-sector fuels (水素・アンモニア発電・混焼).",
        keywords=("水素", "アンモニア")),
    Tag("nuclear", "lowcarbon", "原子力", "Nuclear",
        "Nuclear power: restarts, next-generation reactors, fuel cycle (原子力).",
        keywords=("原子力", "原発", "原子炉", "再稼働", "革新炉", "核燃料")),
)

TAG_KEYS: tuple[str, ...] = tuple(t.key for t in TAGS)
_BY_KEY: dict[str, Tag] = {t.key: t for t in TAGS}
_GROUP_KEYS = {g.key for g in GROUPS}

# Cap on how many tags one meeting can carry. A meeting that matches more than this
# is a broad survey, and a long pill row says nothing.
MAX_MEETING_TAGS = 5

# Score model for a meeting. A hit in a material's title (the agenda item's own name)
# is strong evidence; hits in the briefing body are weaker, because a passing mention
# of 太陽光 in a market-design meeting is not a topic. One title hit is enough on its own;
# the body needs three mentions.
TITLE_WEIGHT = 3
BODY_WEIGHT = 1
TAG_THRESHOLD = 3
# Coverage: how much of a committee's recent work a topic accounts for (see `coverage`).
# Meetings count for less the older they are, measured back from the committee's own
# newest meeting — so a concluded committee keeps its topics rather than fading out.
COVERAGE_HALF_LIFE_DAYS = 365.0
# Shrinkage: this many imaginary meetings with no topic are added to every denominator,
# so one tagged meeting out of one is not "100% of the committee".
COVERAGE_PRIOR = 2.0
# A topic becomes one of a committee's standing tags when its coverage reaches this and
# at least COVERAGE_MIN_MEETINGS meetings carry it (a recurring topic, not a one-off).
COVERAGE_MIN = 0.2
COVERAGE_MIN_MEETINGS = 2


def valid(key: str) -> bool:
    return key in _BY_KEY


def tag_by_key(key: str) -> Tag:
    return _BY_KEY[key]


def normalize(keys: Iterable[str]) -> list[str]:
    """Drop unknown keys and duplicates; return in vocabulary order (stable output)."""
    wanted = {k for k in keys if k in _BY_KEY}
    return [k for k in TAG_KEYS if k in wanted]


def _check_vocabulary() -> None:
    assert len(_BY_KEY) == len(TAGS), "duplicate tag key"
    for t in TAGS:
        assert t.group in _GROUP_KEYS, f"{t.key}: unknown group {t.group}"
        assert t.keywords or t.weak_keywords, f"{t.key}: no keywords"
        assert all(d in _BY_KEY for d in t.defer_to), f"{t.key}: unknown defer_to"
        assert not t.weak_keywords or t.defer_to, f"{t.key}: weak keywords need defer_to"


_check_vocabulary()


def vocabulary() -> dict:
    """The vocabulary as exported to the web (``tagVocab`` in the policy payload)."""
    return {
        "groups": [{"key": g.key, "ja": g.ja, "en": g.en} for g in GROUPS],
        "tags": [{"key": t.key, "group": t.group, "ja": t.ja, "en": t.en} for t in TAGS],
    }


def decode(raw: str | None) -> list[str] | None:
    """A stored tag column (JSON array) as a list of *valid* keys; ``None`` when never tagged.

    Unknown keys are dropped on read, so a tag removed from the vocabulary disappears
    from the export instead of rendering as a raw key.
    """
    if raw is None:
        return None
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(val, list):
        return None
    return normalize(x for x in val if isinstance(x, str))


# ── Keyword matching ─────────────────────────────────────────────────────────
_RX_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern(kw: str) -> re.Pattern[str]:
    rx = _RX_CACHE.get(kw)
    if rx is None:
        if kw.startswith("re:"):
            rx = re.compile(kw[3:])
        elif kw.isascii():
            rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        else:
            rx = re.compile(re.escape(kw))
        _RX_CACHE[kw] = rx
    return rx


def count_hits(text: str, keywords: Iterable[str]) -> int:
    """Total occurrences of *keywords* in *text* (0 for empty text)."""
    if not text:
        return 0
    return sum(len(_pattern(kw).findall(text)) for kw in keywords)


def _scores(texts: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Weighted keyword score per tag over ``(text, weight)`` pairs.

    Two passes so weak keywords can defer to a specific sibling: the sibling's *strong*
    match (not its score) decides, which keeps the result independent of tag order.
    """
    texts = [(t, w) for t, w in texts if t]
    strong: dict[str, int] = {}
    for tag in TAGS:
        s = sum(w * count_hits(t, tag.keywords) for t, w in texts)
        if s:
            strong[tag.key] = s
    out = dict(strong)
    for tag in TAGS:
        if not tag.weak_keywords or any(d in strong for d in tag.defer_to):
            continue
        s = sum(w * count_hits(t, tag.weak_keywords) for t, w in texts)
        if s:
            out[tag.key] = out.get(tag.key, 0) + s
    return out


def tags_from_name(name_ja: str | None) -> list[str]:
    """Committee tags from its Japanese name alone.

    A name is a deliberate statement of scope, so one keyword hit is enough — unlike a
    meeting body, where it takes repetition.
    """
    return normalize(_scores([(name_ja or "", TAG_THRESHOLD)]))


def tags_for_meeting(
    *, titles: Iterable[str] = (), body: str | None = None, extra_title: str | None = None,
) -> list[str]:
    """Rule-based tags for one meeting.

    *titles* are its material titles (agenda item names), *body* its Japanese briefing
    when it has one, *extra_title* the meeting's own title. At most
    :data:`MAX_MEETING_TAGS`, best-scoring first, returned in vocabulary order.
    """
    title_text = "\n".join([t for t in titles if t] + ([extra_title] if extra_title else []))
    scores = _scores([(title_text, TITLE_WEIGHT), (body or "", BODY_WEIGHT)])
    hit = [(k, s) for k, s in scores.items() if s >= TAG_THRESHOLD]
    hit.sort(key=lambda ks: (-ks[1], TAG_KEYS.index(ks[0])))
    return normalize(k for k, _ in hit[:MAX_MEETING_TAGS])


@dataclass(frozen=True)
class Coverage:
    """How much one topic accounts for a committee's meetings.

    ``score`` is in [0, 1) and graded: recency-weighted, shrunk towards zero on thin
    evidence. ``n`` of ``of`` are the plain meeting counts behind it (the evidence a
    reader can check), ``last`` the day of the newest meeting carrying the topic.
    """

    score: float
    n: int
    of: int
    last: date | None


def has_evidence(state: str | None, has_materials: bool) -> bool:
    """Whether a meeting says anything about its committee's topics: it was summarised, or
    at least has documents. A just-detected meeting with neither must not dilute coverage."""
    return state == "done" or has_materials


def coverage(rows: Iterable[tuple[date | None, Iterable[str], bool]]) -> dict[str, Coverage]:
    """Per-topic coverage of one committee from its meetings.

    *rows* is one ``(day, tags, has_evidence)`` per meeting. A meeting with no evidence
    (nothing downloaded or summarised yet) says nothing about the committee and is
    skipped entirely, so a backlog of just-detected meetings cannot dilute a score.

    ``score = Σ w·[topic ∈ meeting] / (Σ w + COVERAGE_PRIOR)`` with
    ``w = ½^(age / COVERAGE_HALF_LIFE_DAYS)``, age counted back from the committee's
    newest dated meeting. Only topics at least one meeting carries appear.
    """
    evidenced = [(d, frozenset(normalize(t))) for d, t, ok in rows if ok]
    if not evidenced:
        return {}
    dated = [d for d, _ in evidenced if d is not None]
    anchor = max(dated) if dated else None
    weights = [
        0.5 ** (max(0, (anchor - d).days) / COVERAGE_HALF_LIFE_DAYS) if anchor and d else 1.0
        for d, _ in evidenced
    ]
    total = sum(weights)
    hit_w: dict[str, float] = {}
    hit_n: dict[str, int] = {}
    last: dict[str, date] = {}
    for (d, tags), w in zip(evidenced, weights, strict=True):
        for k in tags:
            hit_w[k] = hit_w.get(k, 0.0) + w
            hit_n[k] = hit_n.get(k, 0) + 1
            if d is not None and (k not in last or d > last[k]):
                last[k] = d
    return {
        k: Coverage(hit_w[k] / (total + COVERAGE_PRIOR), hit_n[k], len(evidenced), last.get(k))
        for k in TAG_KEYS
        if k in hit_w
    }


def tags_from_coverage(cov: dict[str, Coverage]) -> list[str]:
    """The committee's standing tags implied by its coverage: recurring, not one-off."""
    return normalize(k for k, c in cov.items() if c.score >= COVERAGE_MIN and c.n >= COVERAGE_MIN_MEETINGS)


# ── LLM classification ───────────────────────────────────────────────────────
def classification_question() -> str:
    """The question asked of a meeting's NotebookLM notebook.

    Closed vocabulary with a definition per tag, an explicit evidence bar (an agenda
    item, not a passing mention), and a machine-readable answer.
    """
    lines = [f"- {t.key}: {t.ja} / {t.en} — {t.desc}" for t in TAGS]
    return (
        "Classify this meeting by topic. Use ONLY the tag keys listed below. "
        "Include a tag only if the meeting devoted an agenda item or substantial "
        "discussion to that topic — a passing mention does not count. "
        f"Return at most {MAX_MEETING_TAGS} tags, and an empty list if none apply. "
        'Answer with a single JSON object and nothing else, e.g. {"tags": ["wind_offshore"]}.\n\n'
        "Tags:\n" + "\n".join(lines)
    )


def parse_classification(answer: str | None) -> list[str] | None:
    """Tags from an LLM answer, or ``None`` when it is not a usable answer.

    ``None`` (unparseable) must stay distinct from ``[]`` (a valid "none apply"): the
    caller keeps the rule-based tags for the first and accepts the second.
    Unknown keys are dropped — the model is told to stay inside the vocabulary and is
    not trusted to.
    """
    if not answer:
        return None
    text = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    obj = None
    try:
        obj = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except ValueError:
                obj = None
    if isinstance(obj, dict):
        obj = obj.get("tags")
    if not isinstance(obj, list) or not all(isinstance(x, str) for x in obj):
        return None
    return normalize(obj)[:MAX_MEETING_TAGS]

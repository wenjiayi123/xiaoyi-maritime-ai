"""Render recognized English maritime terms in the vocabulary used by the local Chinese index."""
import re

# Each phrase names a subject, never a document, date, rank or jurisdiction.
# Preserve unmatched substantive words, identifiers, negation, and numbers.
SUBJECTS = (
    (r"international regulations for preventing collisions at sea|collision regulations|collision avoidance rules|rules (?:for|of) (?:the )?road at sea", "海上避碰规则 COLREG"),
    (r"verified gross mass|verified container (?:weight|mass)", "集装箱核实总重 VGM"),
    (r"ballast water management(?: convention)?", "压载水管理公约 BWM"),
    (r"maritime single window", "海事单一窗口"),
    (r"marine (?:environmental )?pollution|pollution of the marine environment|pollution prevention at sea", "海洋污染防治"),
    (r"shore[- ]side (?:power|electricity)|shore power|onshore power supply", "岸电"),
)
VOCABULARY = {
    "chinese":"中国","china":"中国","national":"国家","law":"法律","legislation":"法律","laws":"法律",
    "ship":"船舶","ships":"船舶","vessel":"船舶","vessels":"船舶","port":"港口","ports":"港口",
    "reporting":"申报","packed":"装货","container":"集装箱","containers":"集装箱","lookout":"瞭望",
    "obtained":"取得","governs":"适用","cover":"适用","govern":"适用","regulate":"监管","regulates":"监管",
    "singapore":"新加坡","singaporean":"新加坡","malaysia":"马来西亚","malaysian":"马来西亚",
}
FILLER = set("a an the what which who how is are was were can do does of for at in on to from and by under applies apply applicable relevant".split())


def indexed_query(text):
    if re.search(r"[\u4e00-\u9fff]",text):
        return text
    query = text
    matched = False
    for phrase,replacement in SUBJECTS:
        query,n = re.subn(r"\b(?:"+phrase+r")\b",lambda m:replacement,query,flags=re.I)
        matched |= bool(n)
    if not matched:
        return text
    # Don't split a SOLAS reference or change an unknown product/permit identifier.
    def term(m):
        word=m.group().lower()
        return "" if word in FILLER else VOCABULARY.get(word,m.group())
    query=re.sub(r"[a-zA-Z][a-zA-Z0-9_/-]*",term,query)
    return re.sub(r"\s+"," ",query).strip()

"""Controlled vocabularies: AI/ML signals, role families and the skills taxonomy.

Kept as plain data so the classifier, matcher and UI facets all share one source of truth.
"""

import re

# Title phrases that make a role AI/ML on their own. Weight = how sure we are.
TITLE_SIGNALS: list[tuple[str, float]] = [
    (r"\bmachine[\s-]?learning\b", 1.0),
    (r"\bml\b", 0.9),
    (r"\bmlops\b", 1.0),
    (r"\bllm(s|ops)?\b", 1.0),
    (r"\bgen(erative)?[\s-]?ai\b", 1.0),
    (r"\bdeep[\s-]?learning\b", 1.0),
    (r"\bartificial intelligence\b", 1.0),
    (r"\bai\b", 0.85),
    (r"\bdata scien(ce|tist)s?\b", 1.0),
    (r"\bapplied scien(ce|tist)\b", 1.0),
    (r"\bresearch (scientist|engineer)\b", 0.6),
    (r"\bcomputer vision\b", 1.0),
    (r"\bnlp\b|\bnatural language\b", 1.0),
    (r"\bperception\b", 0.7),
    (r"\bspeech\b", 0.6),
    (r"\brecommend(er|ation)s?\b", 0.7),
    (r"\bprompt engineer", 1.0),
    (r"\bdecision scien", 0.9),
    (r"\bquant(itative)? research", 0.6),
    (r"\bdata (analyst|analytics)\b", 0.55),
    (r"\banalytics engineer\b", 0.55),
    (r"\bdata engineer", 0.5),
    (r"\bbusiness intelligence\b|\bbi (analyst|developer)\b", 0.45),
    (r"\brobotics\b", 0.5),
    (r"\bautonomy\b|\bautonomous\b", 0.5),
]

# Description terms: weaker, counted with diminishing returns.
DESC_SIGNALS: list[str] = [
    r"\bmachine learning\b", r"\bdeep learning\b", r"\bllms?\b", r"\blarge language models?\b",
    r"\bpytorch\b", r"\btensorflow\b", r"\bjax\b", r"\btransformers?\b", r"\bhugging ?face\b",
    r"\brag\b|\bretrieval[- ]augmented\b", r"\bembeddings?\b", r"\bvector (db|database|search)\b",
    r"\bfine[- ]tun(e|ing)\b", r"\bmodel (training|serving|deployment|evaluation)\b",
    r"\bcomputer vision\b", r"\bnlp\b", r"\bgenerative ai\b|\bgenai\b", r"\bai agents?\b|\bagentic\b",
    r"\bscikit[- ]learn\b|\bsklearn\b", r"\bmlops\b", r"\blangchain\b|\bllamaindex\b",
    r"\bopenai\b|\banthropic\b|\bclaude\b|\bgpt-?\d", r"\bneural networks?\b", r"\bxgboost\b",
]

# Ordered: first match wins. (family, title regex)
ROLE_FAMILIES: list[tuple[str, str]] = [
    ("MLOps & ML Platform", r"mlops|ml (platform|infra)|machine learning (platform|infra)|llmops|model serving"),
    ("AI Engineer / LLM", r"\bllm|gen(erative)?[\s-]?ai|prompt|\bai (engineer|developer|application)|agent"),
    ("Computer Vision", r"computer vision|\bcv\b|perception|image|video|imaging"),
    ("NLP & Speech", r"\bnlp\b|natural language|speech|conversational|language model"),
    ("Research", r"research (scientist|engineer|intern|fellow)|applied scien|\bphd\b"),
    ("Data Scientist", r"data scien|decision scien|quant(itative)? (analyst|research)"),
    ("ML Engineer", r"machine[\s-]?learning|\bml\b|deep learning|recommend|\bscientist\b"),
    ("Data & Analytics", r"data (analyst|analytics|engineer)|analytics engineer|business intelligence|\bbi\b"),
    ("AI Product Engineering", r"."),
]

ROLE_FAMILY_NAMES = [f for f, _ in ROLE_FAMILIES]

# Titles that put a role out of scope (0–4 years).
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|manager|vp|vice president|chief|architect|"
    r"distinguished|fellow|expert|iii|iv|level\s*[4-9]|l[5-9]|e[5-9])\b",
    re.I,
)
ENTRY_TITLE = re.compile(
    r"\b(intern(ship)?|trainee|apprentice|graduate|new grad|fresher|entry[\s-]level|junior|jr\.?|associate|"
    r"early career|campus|university|i|level\s*[12]|l[1-3]|e[1-3])\b",
    re.I,
)
INTERN_TITLE = re.compile(r"\b(intern(ship)?|co-?op|apprentice|trainee)\b", re.I)
MID_TITLE = re.compile(r"\b(ii|level\s*3|l4|e4)\b", re.I)

# Canonical skill -> regex. Order matters only for display.
SKILLS: dict[str, str] = {
    "Python": r"\bpython\b",
    "SQL": r"\bsql\b|\bpostgres(ql)?\b|\bmysql\b|\bbigquery\b|\bsnowflake\b",
    "R": r"\bR\b(?= |,|/)",
    "Java": r"\bjava\b(?!script)",
    "Scala": r"\bscala\b",
    "C++": r"c\+\+",
    "Go": r"\bgolang\b|\bgo\b(?= developer| engineer|,)",
    "Rust": r"\brust\b",
    "JavaScript": r"\bjavascript\b",
    "TypeScript": r"\btypescript\b",
    "React": r"\breact(\.js|js)?\b",
    "Next.js": r"\bnext\.?js\b",
    "Node.js": r"\bnode(\.js|js)?\b",
    "PyTorch": r"\bpytorch\b|\btorch\b",
    "TensorFlow": r"\btensorflow\b|\bkeras\b",
    "JAX": r"\bjax\b",
    "scikit-learn": r"\bscikit[- ]learn\b|\bsklearn\b",
    "XGBoost": r"\bxgboost\b|\blightgbm\b|\bcatboost\b|gradient boost",
    "Pandas": r"\bpandas\b",
    "NumPy": r"\bnumpy\b",
    "Matplotlib": r"\bmatplotlib\b|\bseaborn\b|\bplotly\b",
    "Spark": r"\bspark\b|\bpyspark\b|\bdatabricks\b",
    "Airflow": r"\bairflow\b|\bdagster\b|\bprefect\b",
    "dbt": r"\bdbt\b",
    "Kafka": r"\bkafka\b",
    "Hugging Face": r"hugging ?face|\btransformers library\b",
    "LLMs": r"\bllms?\b|large language model|\bgpt\b|\bclaude\b|\bgemini\b|\bllama\b",
    "RAG": r"\brag\b|retrieval[- ]augmented",
    "LangChain": r"\blangchain\b|\blanggraph\b|\bllamaindex\b",
    "AI Agents": r"\bai agents?\b|\bagentic\b|\bmulti-agent\b|\bagents?\b(?= framework| workflow)",
    "Prompt Engineering": r"prompt engineering|\bprompting\b",
    "Fine-tuning": r"fine[- ]tun(e|ing)|\blora\b|\bpeft\b|\brlhf\b",
    "Vector DBs": r"vector (db|database|store|search)|\bpinecone\b|\bweaviate\b|\bfaiss\b|\bpgvector\b|\bqdrant\b|\bchroma\b",
    "NLP": r"\bnlp\b|natural language processing|\btext classification\b|\bner\b",
    "Computer Vision": r"computer vision|\bopencv\b|image (classification|segmentation)|object detection|\byolo",
    "Deep Learning": r"deep learning|neural network|\bcnn\b|\brnn\b|\blstm\b|\btransformer|\byolo",
    "Generative AI": r"generative ai|\bgenai\b|\bgen ai\b|diffusion model|stable diffusion",
    "Statistics": r"\bstatistic(s|al)\b|hypothesis test|a/b test|\bbayesian\b|regression",
    "Machine Learning": r"machine learning|\bml (models?|prediction|pipelines?|projects?|systems?)\b|predictive model|regression model",
    "Time Series": r"time[- ]series|forecasting",
    "Recommender Systems": r"recommend(er|ation) (system|engine)s?|personali[sz]ation",
    "EDA": r"\beda\b|exploratory data analysis",
    "Data Visualization": r"data visuali[sz]ation|\btableau\b|power ?bi|\blooker\b|dashboards?",
    "Excel": r"\bexcel\b|spreadsheets?",
    "MLOps": r"\bmlops\b|\bmlflow\b|\bkubeflow\b|weights (&|and) biases|\bwandb\b|model monitoring",
    "Docker": r"\bdocker\b|container",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "AWS": r"\baws\b|sagemaker|amazon web services|\bs3\b|\blambda\b",
    "GCP": r"\bgcp\b|google cloud|vertex ai",
    "Azure": r"\bazure\b",
    "FastAPI": r"\bfastapi\b|\bflask\b|\bdjango\b",
    "Git": r"\bgit\b|github|gitlab",
    "Linux": r"\blinux\b|\bbash\b",
    "CUDA": r"\bcuda\b|\bgpu programming\b|\btriton\b",
    "Reinforcement Learning": r"reinforcement learning|\brl\b(?= |,)",
    "Speech": r"\bspeech\b|\basr\b|\btts\b|text[- ]to[- ]speech",
    "Data Engineering": r"\betl\b|\belt\b|data pipelines?|data warehouse",
}

COMPILED_SKILLS = {name: re.compile(rx, re.I if name != "R" else 0) for name, rx in SKILLS.items()}


def _split_top(pattern: str) -> list[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            cur += pattern[i: i + 2]
            i += 2
            continue
        depth += ch == "("
        depth -= ch == ")"
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    return parts + [cur]


def _mandatory_word(alt: str) -> str | None:
    """Longest literal word that every match of this alternative must contain."""
    s = re.sub(r"\\[bBdDsSwW]", " ", alt)      # \b \s … carry no literal text
    s = re.sub(r"\\(.)", r"\1", s)             # \. \+ -> literal
    s = re.sub(r"\[[^\]]*\]", " ", s)           # character classes
    prev = None
    while prev != s:                            # drop every group: its content may be optional
        prev = s
        s = re.sub(r"\([^()]*\)", " ", s)
    s = re.sub(r".[?*]|\{\d*,?\d*\}", " ", s)   # optional / repeated chars
    words = re.findall(r"[a-z0-9+#]{3,}", s.lower())
    return max(words, key=len) if words else None


class Prefiltered:
    """A regex guarded by cheap substring checks. Each top-level alternative contributes one
    word its matches must contain; if none of those appear, the regex cannot match, so the
    expensive scan is skipped. Alternatives without a mandatory word disable the filter."""

    __slots__ = ("rx", "triggers", "folded")

    def __init__(self, pattern: str, flags: int = re.I):
        # Case-insensitive patterns run against the pre-lowered text without re.I, which is
        # several times faster in CPython's regex engine.
        self.folded = bool(flags & re.I)
        self.rx = re.compile(pattern.lower() if self.folded else pattern, flags & ~re.I)
        words = [_mandatory_word(a) for a in _split_top(pattern)]
        self.triggers = tuple({w[:6] for w in words}) if all(words) and self.folded else ()

    def search(self, text: str, low: str | None = None):
        if not self.folded:
            return self.rx.search(text)
        low = low if low is not None else text.lower()
        if self.triggers and not any(t in low for t in self.triggers):
            return None
        return self.rx.search(low)


PREFILTERED_SKILLS = {name: Prefiltered(rx, re.I if name != "R" else 0) for name, rx in SKILLS.items()}

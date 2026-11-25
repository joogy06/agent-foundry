"""Coding tasks for local_bench.py: each task is a prompt, the name of what the answer must define,
graded test cases (each one a small block of Python that raises on failure) and a reference
solution that must pass every case (tests/test_local_bench.py holds the tasks to that).

The long-context task (`build_longctx`) hides three business rules in a large synthetic codebase at
different depths, plus one retired rule as a distractor, and asks for a function that uses them.
"""
import random

TASKS = [
    {
        "id": "m-merge-intervals", "difficulty": "medium", "defines": "merge_intervals",
        "prompt": (
            "Write a Python function `merge_intervals(intervals)` that takes a list of closed integer "
            "intervals as (start, end) tuples, in any order, and returns a new sorted list of tuples where "
            "overlapping intervals and intervals that touch (end == next start) are merged. An interval with "
            "start > end is invalid: raise ValueError. An empty list returns []. Do not modify the input."),
        "tests": [
            "assert merge_intervals([]) == []",
            "assert merge_intervals([(1, 3), (2, 6), (8, 10), (15, 18)]) == [(1, 6), (8, 10), (15, 18)]",
            "assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]",
            "assert merge_intervals([(5, 7), (1, 2)]) == [(1, 2), (5, 7)]",
            "assert merge_intervals([(1, 10), (2, 3), (4, 5)]) == [(1, 10)]",
            "assert merge_intervals([(4, 4), (4, 4)]) == [(4, 4)]",
            "x = [(3, 4), (1, 2)]\nmerge_intervals(x)\nassert x == [(3, 4), (1, 2)]",
            "try:\n    merge_intervals([(5, 1)])\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
        ],
        "reference": (
            "def merge_intervals(intervals):\n"
            "    for s, e in intervals:\n"
            "        if s > e:\n            raise ValueError('bad interval')\n"
            "    out = []\n"
            "    for s, e in sorted(intervals):\n"
            "        if out and s <= out[-1][1]:\n            out[-1] = (out[-1][0], max(out[-1][1], e))\n"
            "        else:\n            out.append((s, e))\n"
            "    return out\n"),
    },
    {
        "id": "m-lru-cache", "difficulty": "medium", "defines": "LRUCache",
        "prompt": (
            "Write a Python class `LRUCache` with `__init__(self, capacity)`, `get(self, key)` (returns the value, "
            "or -1 when absent; a hit makes the key most recently used) and `put(self, key, value)` (inserts or "
            "updates and makes the key most recently used; when over capacity it evicts the least recently used "
            "key). Capacity 0 stores nothing. A negative capacity raises ValueError. All operations O(1)."),
        "tests": [
            "c = LRUCache(2); c.put(1, 1); c.put(2, 2); assert c.get(1) == 1; c.put(3, 3); assert c.get(2) == -1",
            "c = LRUCache(2); c.put(1, 1); c.put(2, 2); c.put(1, 10); c.put(3, 3); assert c.get(1) == 10; assert c.get(2) == -1",
            "c = LRUCache(0); c.put(1, 1); assert c.get(1) == -1",
            "c = LRUCache(1); c.put(1, 1); c.put(2, 2); assert c.get(1) == -1 and c.get(2) == 2",
            "c = LRUCache(3)\nfor i in range(3): c.put(i, i)\nc.get(0); c.put(9, 9)\nassert c.get(1) == -1 and c.get(0) == 0 and c.get(2) == 2",
            "c = LRUCache(2); assert c.get('missing') == -1",
            "try:\n    LRUCache(-1)\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
        ],
        "reference": (
            "from collections import OrderedDict\n"
            "class LRUCache:\n"
            "    def __init__(self, capacity):\n"
            "        if capacity < 0:\n            raise ValueError('capacity')\n"
            "        self.cap = capacity; self.d = OrderedDict()\n"
            "    def get(self, key):\n"
            "        if key not in self.d:\n            return -1\n"
            "        self.d.move_to_end(key); return self.d[key]\n"
            "    def put(self, key, value):\n"
            "        if self.cap == 0:\n            return\n"
            "        self.d[key] = value; self.d.move_to_end(key)\n"
            "        if len(self.d) > self.cap:\n            self.d.popitem(last=False)\n"),
    },
    {
        "id": "m-roman", "difficulty": "medium", "defines": "int_to_roman, roman_to_int",
        "prompt": (
            "Write two Python functions. `int_to_roman(n)` converts an integer 1..3999 to standard Roman numerals "
            "(subtractive forms IV, IX, XL, XC, CD, CM) and raises ValueError outside that range or for a "
            "non-int. `roman_to_int(s)` converts a string back and raises ValueError for anything that is not the "
            "canonical numeral of some 1..3999 value (for example 'IIII', 'IC', 'VX', 'MMMM', '', 'iv')."),
        "tests": [
            "assert int_to_roman(1994) == 'MCMXCIV' and int_to_roman(3999) == 'MMMCMXCIX' and int_to_roman(4) == 'IV'",
            "assert roman_to_int('MCMXCIV') == 1994 and roman_to_int('LVIII') == 58",
            "assert all(roman_to_int(int_to_roman(i)) == i for i in range(1, 4000))",
            "for bad in ['IIII', 'IC', 'VX', 'MMMM', '', 'iv', 'IIV', 'XM', 'VV']:\n    try:\n        roman_to_int(bad)\n        raise AssertionError(bad)\n    except ValueError:\n        pass",
            "for bad in [0, 4000, -5]:\n    try:\n        int_to_roman(bad)\n        raise AssertionError(bad)\n    except ValueError:\n        pass",
        ],
        "reference": (
            "_V = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n"
            "def int_to_roman(n):\n"
            "    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 3999:\n        raise ValueError(n)\n"
            "    out = ''\n"
            "    for v, s in _V:\n"
            "        while n >= v:\n            out += s; n -= v\n"
            "    return out\n"
            "_R = {int_to_roman(i): i for i in range(1, 4000)}\n"
            "def roman_to_int(s):\n"
            "    if s not in _R:\n        raise ValueError(s)\n"
            "    return _R[s]\n"),
    },
    {
        "id": "m-wordwrap", "difficulty": "medium", "defines": "wrap",
        "prompt": (
            "Write a Python function `wrap(text, width)` that returns a list of lines. Words are separated by any "
            "whitespace (collapse runs of whitespace, ignore leading/trailing). Fill greedily: put as many words "
            "on a line as fit, joined by single spaces, with no line longer than `width`. A word longer than "
            "`width` is split into chunks of exactly `width` characters (the last chunk may be shorter); each "
            "chunk is placed like a word, so a short last chunk may share a line with the following words. Empty "
            "or whitespace-only text returns []. width < 1 raises ValueError."),
        "tests": [
            "assert wrap('', 5) == [] and wrap('   ', 5) == []",
            "assert wrap('the quick brown fox', 10) == ['the quick', 'brown fox']",
            "assert wrap('a  b\\n\\tc', 3) == ['a b', 'c']",
            "assert wrap('abcdefghij', 4) == ['abcd', 'efgh', 'ij']",
            "assert wrap('abcdefghij k', 4) == ['abcd', 'efgh', 'ij k']",
            "assert wrap('hello world', 11) == ['hello world']",
            "assert all(len(l) <= 7 for l in wrap('lorem ipsum dolor sit amet consectetur adipiscing', 7))",
            "try:\n    wrap('x', 0)\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
        ],
        "reference": (
            "def wrap(text, width):\n"
            "    if width < 1:\n        raise ValueError(width)\n"
            "    pieces = []\n"
            "    for w in text.split():\n"
            "        pieces.extend(w[i:i + width] for i in range(0, len(w), width))\n"
            "    lines = []\n"
            "    for p in pieces:\n"
            "        if lines and len(lines[-1]) + 1 + len(p) <= width:\n            lines[-1] += ' ' + p\n"
            "        else:\n            lines.append(p)\n"
            "    return lines\n"),
    },
    {
        "id": "h-regex", "difficulty": "hard", "defines": "full_match",
        "prompt": (
            "Write a Python function `full_match(pattern, s)` returning True when the whole string `s` matches "
            "`pattern`, without using the `re` module. Supported syntax: a literal character; `.` (any one "
            "character); the postfix quantifiers `*` (zero or more), `+` (one or more) and `?` (zero or one), each "
            "applying to the single preceding atom (a literal, `.`, or an escaped character); and `\\\\` escaping "
            "the next character so it is literal (e.g. `\\\\.` matches only '.', `\\\\*` only '*'). A quantifier "
            "with no preceding atom, two quantifiers in a row, or a trailing lone backslash raises ValueError. "
            "It must not take exponential time on patterns like 'a*a*a*a*a*a*a*a*b' against 30 'a's."),
        "tests": [
            "assert full_match('a.c', 'abc') and not full_match('a.c', 'abcd')",
            "assert full_match('a*', '') and full_match('a*', 'aaaa') and not full_match('a+', '')",
            "assert full_match('colou?r', 'color') and full_match('colou?r', 'colour') and not full_match('colou?r', 'colouur')",
            "assert full_match('.*x.+', 'abxyz') and not full_match('.*x.+', 'abx')",
            "assert full_match('a\\\\.b', 'a.b') and not full_match('a\\\\.b', 'axb')",
            "assert full_match('\\\\*+', '***') and not full_match('\\\\*+', '')",
            "assert full_match('\\\\\\\\', '\\\\')",
            "import time\nt = time.time()\nassert not full_match('a*a*a*a*a*a*a*a*b', 'a' * 30)\nassert time.time() - t < 2",
            "for bad in ['*a', 'a**', 'a+?', 'ab\\\\']:\n    try:\n        full_match(bad, 'a')\n        raise AssertionError(bad)\n    except ValueError:\n        pass",
        ],
        "reference": (
            "def full_match(pattern, s):\n"
            "    atoms = []\n"
            "    i = 0\n"
            "    while i < len(pattern):\n"
            "        c = pattern[i]\n"
            "        if c in '*+?':\n"
            "            if not atoms or atoms[-1][1] is not None:\n                raise ValueError(pattern)\n"
            "            atoms[-1] = (atoms[-1][0], c); i += 1; continue\n"
            "        if c == '\\\\':\n"
            "            if i + 1 >= len(pattern):\n                raise ValueError(pattern)\n"
            "            atoms.append(((False, pattern[i + 1]), None)); i += 2; continue\n"
            "        atoms.append(((c == '.', c), None)); i += 1\n"
            "    from functools import lru_cache\n"
            "    def ok(atom, ch):\n        return atom[0] or atom[1] == ch\n"
            "    @lru_cache(maxsize=None)\n"
            "    def m(ai, si):\n"
            "        if ai == len(atoms):\n            return si == len(s)\n"
            "        atom, q = atoms[ai]\n"
            "        first = si < len(s) and ok(atom, s[si])\n"
            "        if q is None:\n            return first and m(ai + 1, si + 1)\n"
            "        if q == '?':\n            return m(ai + 1, si) or (first and m(ai + 1, si + 1))\n"
            "        if q == '*':\n            return m(ai + 1, si) or (first and m(ai, si + 1))\n"
            "        return first and (m(ai, si + 1) or m(ai + 1, si + 1))\n"
            "    return m(0, 0)\n"),
    },
    {
        "id": "h-calc", "difficulty": "hard", "defines": "evaluate",
        "prompt": (
            "Write a Python function `evaluate(expr)` that evaluates an arithmetic expression string exactly and "
            "returns a `fractions.Fraction`. Grammar: non-negative integer literals, binary `+ - * /` with the usual "
            "precedence and left associativity, unary minus and unary plus (which may repeat, e.g. '--3'), "
            "parentheses, and arbitrary whitespace between tokens. Division is exact (Fraction). Division by zero "
            "raises ZeroDivisionError. Anything malformed (empty string, unbalanced parentheses, a dangling "
            "operator, two numbers in a row such as '1 2', unknown characters) raises ValueError. Do not use "
            "eval, exec, ast or compile."),
        "tests": [
            "from fractions import Fraction as F\nassert evaluate('1 + 2 * 3') == 7 and evaluate('(1 + 2) * 3') == 9",
            "from fractions import Fraction as F\nassert evaluate('7 / 2') == F(7, 2) and evaluate('1/3 + 1/6') == F(1, 2)",
            "assert evaluate('10 - 4 - 3') == 3 and evaluate('64 / 4 / 2') == 8",
            "assert evaluate('-3 * -(2 + 1)') == 9 and evaluate('--3') == 3 and evaluate('+4 - -1') == 5",
            "assert evaluate('  ( ( 42 ) ) ') == 42",
            "from fractions import Fraction as F\nassert isinstance(evaluate('6/3'), F)",
            "try:\n    evaluate('1/(2-2)')\n    raise AssertionError('no ZeroDivisionError')\nexcept ZeroDivisionError:\n    pass",
            "for bad in ['', '1 +', '(1 + 2', '1 + 2)', '1 2', '2 * * 3', '3 % 2', '()', 'abc']:\n    try:\n        evaluate(bad)\n        raise AssertionError(bad)\n    except ValueError:\n        pass",
        ],
        "reference": (
            "from fractions import Fraction\n"
            "def evaluate(expr):\n"
            "    toks = []\n"
            "    i = 0\n"
            "    while i < len(expr):\n"
            "        c = expr[i]\n"
            "        if c.isspace():\n            i += 1\n"
            "        elif c.isdigit():\n"
            "            j = i\n"
            "            while j < len(expr) and expr[j].isdigit():\n                j += 1\n"
            "            toks.append(int(expr[i:j])); i = j\n"
            "        elif c in '+-*/()':\n            toks.append(c); i += 1\n"
            "        else:\n            raise ValueError(c)\n"
            "    pos = [0]\n"
            "    def peek():\n        return toks[pos[0]] if pos[0] < len(toks) else None\n"
            "    def take():\n        t = peek(); pos[0] += 1; return t\n"
            "    def expr_():\n"
            "        v = term()\n"
            "        while peek() in ('+', '-'):\n"
            "            op = take(); r = term(); v = v + r if op == '+' else v - r\n"
            "        return v\n"
            "    def term():\n"
            "        v = unary()\n"
            "        while peek() in ('*', '/'):\n"
            "            op = take(); r = unary()\n"
            "            if op == '*':\n                v = v * r\n"
            "            else:\n"
            "                if r == 0:\n                    raise ZeroDivisionError('division by zero')\n"
            "                v = v / r\n"
            "        return v\n"
            "    def unary():\n"
            "        if peek() in ('+', '-'):\n"
            "            op = take(); v = unary(); return v if op == '+' else -v\n"
            "        return atom()\n"
            "    def atom():\n"
            "        t = take()\n"
            "        if isinstance(t, int):\n            return Fraction(t)\n"
            "        if t == '(':\n"
            "            v = expr_()\n"
            "            if take() != ')':\n                raise ValueError('paren')\n"
            "            return v\n"
            "        raise ValueError(t)\n"
            "    v = expr_()\n"
            "    if pos[0] != len(toks):\n        raise ValueError('trailing')\n"
            "    return v\n"),
    },
    {
        "id": "h-course-order", "difficulty": "hard", "defines": "course_order",
        "prompt": (
            "Write a Python function `course_order(n, prereqs)` for courses numbered 0..n-1, where `prereqs` is a "
            "list of pairs (a, b) meaning course b must be taken before course a. Return the lexicographically "
            "smallest valid order (a list of all n courses) among all orders that respect every prerequisite. If "
            "the prerequisites contain a cycle, raise ValueError. A pair naming a course outside 0..n-1 raises "
            "ValueError. Duplicate pairs are allowed. It must handle n = 100000 with 200000 pairs in a few seconds."),
        "tests": [
            "assert course_order(0, []) == [] and course_order(3, []) == [0, 1, 2]",
            "assert course_order(4, [(1, 0), (2, 0), (3, 1), (3, 2)]) == [0, 1, 2, 3]",
            "assert course_order(3, [(0, 2)]) == [1, 2, 0]",
            "assert course_order(4, [(0, 3), (0, 3), (1, 3)]) == [2, 3, 0, 1]",
            "try:\n    course_order(2, [(0, 1), (1, 0)])\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
            "try:\n    course_order(2, [(0, 5)])\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
            "import random, time\nr = random.Random(1); n = 100000\nps = [(r.randrange(1, n), 0) for _ in range(200000)]\nt = time.time(); o = course_order(n, ps)\nassert o[0] == 0 and len(o) == n and time.time() - t < 5",
        ],
        "reference": (
            "import heapq\n"
            "def course_order(n, prereqs):\n"
            "    adj = [[] for _ in range(n)]; indeg = [0] * n\n"
            "    for a, b in prereqs:\n"
            "        if not (0 <= a < n and 0 <= b < n):\n            raise ValueError((a, b))\n"
            "        adj[b].append(a); indeg[a] += 1\n"
            "    h = [i for i in range(n) if indeg[i] == 0]; heapq.heapify(h); out = []\n"
            "    while h:\n"
            "        u = heapq.heappop(h); out.append(u)\n"
            "        for v in adj[u]:\n"
            "            indeg[v] -= 1\n"
            "            if indeg[v] == 0:\n                heapq.heappush(h, v)\n"
            "    if len(out) != n:\n        raise ValueError('cycle')\n"
            "    return out\n"),
    },
    {
        "id": "h-cheapest-flight", "difficulty": "hard", "defines": "cheapest",
        "prompt": (
            "Write a Python function `cheapest(n, flights, src, dst, k)` for cities 0..n-1, where `flights` is a "
            "list of (from, to, price) with non-negative integer prices (there may be several flights between the "
            "same pair). Return the minimum total price from src to dst using at most k intermediate stops (so at "
            "most k + 1 flights), or -1 if impossible. src == dst returns 0. k < 0 raises ValueError. It must be "
            "efficient for n = 2000, 20000 flights, k = 50."),
        "tests": [
            "assert cheapest(4, [(0,1,100),(1,2,100),(2,0,100),(1,3,600),(2,3,200)], 0, 3, 1) == 700",
            "assert cheapest(4, [(0,1,100),(1,2,100),(2,0,100),(1,3,600),(2,3,200)], 0, 3, 2) == 400",
            "assert cheapest(3, [(0,1,100),(1,2,100),(0,2,500)], 0, 2, 0) == 500",
            "assert cheapest(3, [(0,1,100)], 0, 2, 5) == -1 and cheapest(3, [], 1, 1, 0) == 0",
            "assert cheapest(2, [(0,1,50),(0,1,20)], 0, 1, 0) == 20",
            "assert cheapest(4, [(0,1,1),(1,2,1),(2,3,1),(0,3,10)], 0, 3, 1) == 10",
            "try:\n    cheapest(2, [], 0, 1, -1)\n    raise AssertionError('no ValueError')\nexcept ValueError:\n    pass",
            "import random, time\nr = random.Random(2); n = 2000\nfl = [(r.randrange(n), r.randrange(n), r.randrange(1, 1000)) for _ in range(20000)]\nt = time.time(); v = cheapest(n, fl, 0, 1999, 50)\nassert isinstance(v, int) and time.time() - t < 10",
        ],
        "reference": (
            "def cheapest(n, flights, src, dst, k):\n"
            "    if k < 0:\n        raise ValueError(k)\n"
            "    if src == dst:\n        return 0\n"
            "    INF = float('inf'); best = [INF] * n; best[src] = 0\n"
            "    for _ in range(k + 1):\n"
            "        nxt = best[:]\n"
            "        for a, b, p in flights:\n"
            "            if best[a] + p < nxt[b]:\n                nxt[b] = best[a] + p\n"
            "        best = nxt\n"
            "    return -1 if best[dst] == INF else int(best[dst])\n"),
    },
]

# ---- long-context coding task ---------------------------------------------------------------

LONGCTX_SUPPORT = (
    "TAX_RATES = {'UK': 20, 'DE': 19, 'FR': 20, 'US': 0}\n"
    "def round_pence(value):\n"
    "    from fractions import Fraction\n"
    "    v = Fraction(value)\n"
    "    return int(v + Fraction(1, 2)) if v >= 0 else -int(-v + Fraction(1, 2))\n"
    "def shipping_cost(weight_grams):\n"
    "    if weight_grams <= 0:\n        return 0\n"
    "    return 399 + 150 * ((weight_grams - 1) // 1000)\n"
)

LONGCTX_PROMPT_TAIL = (
    "Task: implement `invoice_total(items, country, prior_orders)` for billing/invoice.py so that it is "
    "consistent with every billing rule stated in the codebase above (the rules are spread across several "
    "files; read the comments and docstrings, and ignore rules marked as retired). `items` is a list of "
    "(unit_price_pence, quantity, weight_grams_each). Return the total in integer pence. You may call "
    "TAX_RATES, round_pence and shipping_cost from the billing package as if they were already imported. "
    "An unknown country raises KeyError. Answer with one ```python code block containing the function (and "
    "nothing it depends on beyond those three names)."
)

LONGCTX_FACTS = [
    ("billing/config.py",
     "# Billing configuration.\n# TAX_RATES are percentages applied by invoice_total.\n" + LONGCTX_SUPPORT.split("def round_pence")[0]),
    ("billing/legacy_notes.py",
     '"""RETIRED 2025-03: the old loyalty rule (5% off for customers with 3 or more prior orders)\n'
     'was removed and must not be used. The current rule lives in billing/discounts.py."""\n'),
    ("billing/discounts.py",
     '"""Loyalty discount (current rule): a customer with 5 or more prior orders gets 7% off the\n'
     'goods subtotal (sum of unit price x quantity). The discount is computed with round_pence and\n'
     'subtracted before shipping and tax are worked out."""\n'),
    ("billing/shipping.py",
     '"""Free shipping: when the discounted goods subtotal is 5000 pence or more, shipping is 0.\n'
     'Otherwise shipping is shipping_cost(total weight in grams of all items).\nTax is charged on\n'
     '(discounted subtotal + shipping) at TAX_RATES[country] percent, rounded with round_pence,\n'
     'and added last."""\n' + "def round_pence" + LONGCTX_SUPPORT.split("def round_pence")[1]),
]

LONGCTX_REFERENCE = (
    "def invoice_total(items, country, prior_orders):\n"
    "    rate = TAX_RATES[country]\n"
    "    sub = sum(p * q for p, q, _ in items)\n"
    "    if prior_orders >= 5:\n        sub -= round_pence(sub * 7 / 100)\n"
    "    ship = 0 if sub >= 5000 else shipping_cost(sum(w * q for _, q, w in items))\n"
    "    base = sub + ship\n"
    "    return base + round_pence(base * rate / 100)\n"
)

LONGCTX_TESTS = [
    "assert invoice_total([(1000, 2, 500)], 'UK', 0) == round_pence((2000 + shipping_cost(1000)) * 120 / 100)",
    "assert invoice_total([(2500, 2, 300)], 'DE', 0) == 5950",
    "assert invoice_total([(1000, 5, 100)], 'UK', 5) == 6059",
    "assert invoice_total([(1000, 5, 100)], 'UK', 4) == 6000",
    "assert invoice_total([(1000, 5, 100)], 'US', 3) == 5000",
    "assert invoice_total([(999, 3, 1200)], 'FR', 7) == 4363",
    "assert invoice_total([], 'UK', 0) == 0",
    "try:\n    invoice_total([(100, 1, 1)], 'XX', 0)\n    raise AssertionError('no KeyError')\nexcept KeyError:\n    pass",
]

_WORDS = ("ledger account batch record export parse cursor buffer report schema queue retry token "
          "window shard index cache merge filter render audit client region payload").split()


def _filler_module(rng, idx):
    name = f"{rng.choice(_WORDS)}_{rng.choice(_WORDS)}_{idx}"
    lines = [f'"""Module {name}: helpers for {rng.choice(_WORDS)} {rng.choice(_WORDS)} handling."""', ""]
    for f in range(rng.randint(3, 6)):
        fn = f"{rng.choice(_WORDS)}_{rng.choice(_WORDS)}_{idx}_{f}"
        a, b = rng.randint(2, 97), rng.randint(1, 50)
        lines += [
            f"def {fn}(values, limit={b}):",
            f'    """Return the {rng.choice(_WORDS)} {rng.choice(_WORDS)} of values, capped at limit."""',
            "    out = []",
            "    for v in values:",
            f"        if v % {a} == {a // 3}:",
            "            continue",
            f"        out.append(min(v * {a} + {b}, limit))",
            "    return out", ""]
    return name, "\n".join(lines)


def build_longctx(target_chars, seed=11):
    """Return (prompt, answer_prefix_code) with the facts placed at depths 0.15/0.35/0.55/0.85."""
    rng = random.Random(seed)
    files, size, i = [], 0, 0
    while size < target_chars:
        name, body = _filler_module(rng, i)
        files.append((f"pkg/{name}.py", body)); size += len(body) + 40; i += 1
    for depth, (path, body) in zip((0.15, 0.35, 0.55, 0.85), LONGCTX_FACTS):
        files.insert(int(len(files) * depth), (path, body))
    text = "".join(f"\n=== FILE: {p} ===\n{b}\n" for p, b in files)
    prompt = ("Below is a Python codebase, one file after another.\n<codebase>" + text + "</codebase>\n\n"
              + LONGCTX_PROMPT_TAIL)
    return prompt

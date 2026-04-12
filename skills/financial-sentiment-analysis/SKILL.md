---
name: financial-sentiment-analysis
description: Use when analysing financial text sentiment using FinBERT or LLMs, building sentiment scoring pipelines for news/earnings/social media, extracting financial entities, or normalising sentiment signals for trading use
---

# Financial Sentiment Analysis

## Overview

Financial sentiment analysis converts unstructured text (news, earnings calls, social media) into quantitative signals. **FinBERT** is the go-to model for labelled sentiment; **LLMs** (Qwen, Claude) are used for structured reasoning and entity extraction.

**Core principle:** Raw sentiment scores are noisy. Always normalise, smooth, and decay-weight before using as trading signals.

## When to Use

- Processing news headlines, earnings call transcripts, SEC filings
- Building sentiment features for trading models
- Extracting named entities (companies, people, events) from financial text
- Evaluating LLM-based financial reasoning pipelines

## FinBERT Deployment

```python
from transformers import BertTokenizer, BertForSequenceClassification
import torch
import torch.nn.functional as F
from typing import Union

class FinBERTSentiment:
    """
    FinBERT: ProsusAI/finbert
    Labels: positive, negative, neutral
    """
    MODEL_ID = "ProsusAI/finbert"
    LABELS   = ['positive', 'negative', 'neutral']

    def __init__(self, device: str = 'auto'):
        self.device = (torch.device('cuda') if torch.cuda.is_available()
                       else torch.device('cpu')) if device == 'auto' else torch.device(device)
        self.tokenizer = BertTokenizer.from_pretrained(self.MODEL_ID)
        self.model = BertForSequenceClassification.from_pretrained(self.MODEL_ID)
        self.model.to(self.device)
        self.model.eval()

    def score(self, text: Union[str, list[str]]) -> list[dict]:
        """Returns list of {positive, negative, neutral, label, compound} dicts."""
        if isinstance(text, str):
            text = [text]

        # Truncate to 512 tokens (FinBERT max)
        inputs = self.tokenizer(
            text, return_tensors='pt', truncation=True,
            max_length=512, padding=True
        ).to(self.device)

        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = F.softmax(logits, dim=-1).cpu().numpy()

        results = []
        for p in probs:
            scores = dict(zip(self.LABELS, p.tolist()))
            scores['label'] = self.LABELS[p.argmax()]
            # Compound score: positive - negative, range [-1, 1]
            scores['compound'] = scores['positive'] - scores['negative']
            results.append(scores)

        return results

    def score_batch(self, texts: list[str], batch_size: int = 32) -> list[dict]:
        """Memory-efficient batch processing."""
        results = []
        for i in range(0, len(texts), batch_size):
            results.extend(self.score(texts[i:i + batch_size]))
        return results
```

## Financial Text Preprocessing

```python
import re

FINANCIAL_CONTRACTIONS = {
    'Q1': 'first quarter', 'Q2': 'second quarter',
    'YoY': 'year over year', 'QoQ': 'quarter over quarter',
    'EPS': 'earnings per share', 'FCF': 'free cash flow',
}

def preprocess_financial_text(text: str) -> str:
    """Normalise financial text before embedding or scoring."""
    # Remove boilerplate disclaimers
    text = re.sub(r'(?i)forward.looking statement.{0,200}', '', text)
    text = re.sub(r'(?i)safe harbor.{0,200}', '', text)

    # Normalise numbers: "$1.2B" -> "1.2 billion dollars"
    text = re.sub(r'\$(\d+\.?\d*)([BMK])',
        lambda m: f"{m.group(1)} {'billion' if m.group(2)=='B' else 'million' if m.group(2)=='M' else 'thousand'} dollars",
        text)

    # Normalise percentages: "up 3.5%" -> "increased 3.5 percent"
    text = re.sub(r'up (\d+\.?\d*)%', r'increased \1 percent', text)
    text = re.sub(r'down (\d+\.?\d*)%', r'decreased \1 percent', text)
    text = re.sub(r'(\d+\.?\d*)%', r'\1 percent', text)

    # Expand contractions
    for abbr, expanded in FINANCIAL_CONTRACTIONS.items():
        text = re.sub(r'\b' + abbr + r'\b', expanded, text)

    # Collapse whitespace
    return ' '.join(text.split())
```

## LLM-Based Analysis (Qwen/Claude)

```python
import json

FINANCIAL_ANALYSIS_PROMPT = """Analyse this financial text and respond with JSON only.

Text: {text}

Respond with:
{{
  "sentiment": "bullish|bearish|neutral",
  "confidence": 0.0-1.0,
  "key_entities": [
    {{"name": "...", "type": "company|person|event|metric", "sentiment": "positive|negative|neutral"}}
  ],
  "key_claims": ["..."],
  "risk_factors": ["..."],
  "time_horizon": "short_term|medium_term|long_term|unspecified"
}}"""

async def llm_financial_analysis(text: str, llm_client) -> dict:
    """Use LLM for structured financial analysis."""
    response = await llm_client.complete(
        FINANCIAL_ANALYSIS_PROMPT.format(text=text[:4000]),  # truncate context
        temperature=0.1,  # low temperature for structured output
    )
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        # Extract JSON from response if wrapped in markdown
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group()) if match else {}
```

## Signal Normalisation Pipeline

```python
import pandas as pd
import numpy as np

def build_sentiment_signal(
    raw_scores: pd.Series,         # compound scores, indexed by datetime
    smoothing_window: int = 24,    # hours for EMA
    decay_halflife: int = 12,      # hours until signal halves
    clip_std: float = 2.0,         # clip outliers beyond 2 std
) -> pd.Series:
    """
    Converts raw FinBERT compound scores to a normalised trading signal.
    Output: z-score clipped to [-1, 1].
    """
    # Exponential moving average (smoothing)
    smoothed = raw_scores.ewm(span=smoothing_window).mean()

    # Z-score normalisation (rolling 30-day window)
    rolling_mean = smoothed.rolling(window=30*24).mean()
    rolling_std  = smoothed.rolling(window=30*24).std()
    z_scored = (smoothed - rolling_mean) / (rolling_std + 1e-8)

    # Clip outliers
    clipped = z_scored.clip(-clip_std, clip_std) / clip_std

    return clipped

def aggregate_multi_source(
    sources: dict[str, pd.Series],  # {'reuters': scores, 'twitter': scores}
    weights: dict[str, float],       # {'reuters': 0.6, 'twitter': 0.4}
) -> pd.Series:
    """Weighted aggregate of multiple sentiment sources, resampled to hourly."""
    dfs = []
    for source, scores in sources.items():
        w = weights.get(source, 1.0 / len(sources))
        dfs.append(scores.resample('1h').mean().fillna(method='ffill') * w)
    return pd.concat(dfs, axis=1).sum(axis=1)
```

## Entity Extraction Pattern

```python
import spacy

# Use en_core_web_sm + custom financial entity patterns
nlp = spacy.load('en_core_web_sm')

FINANCIAL_ENTITIES = [
    ('FED', r'(?i)(federal reserve|fed rate|FOMC)'),
    ('EARNINGS', r'(?i)(earnings per share|EPS|revenue|profit)'),
    ('MERGER', r'(?i)(acquisition|merger|takeover|buyout)'),
]

def extract_financial_entities(text: str) -> list[dict]:
    doc = nlp(text)
    entities = [
        {'text': ent.text, 'label': ent.label_, 'start': ent.start_char}
        for ent in doc.ents
        if ent.label_ in ('ORG', 'PERSON', 'GPE', 'MONEY', 'PERCENT')
    ]
    # Add custom financial event patterns
    for label, pattern in FINANCIAL_ENTITIES:
        for match in re.finditer(pattern, text):
            entities.append({'text': match.group(), 'label': label,
                             'start': match.start()})
    return sorted(entities, key=lambda x: x['start'])
```

## Quick Reference — Model Comparison

| Model | Accuracy | Speed | Use Case |
|-------|---------|-------|----------|
| FinBERT | ~85% on FPB | Fast (GPU) | High-volume news scoring |
| RoBERTa-finance | ~87% | Moderate | Higher accuracy requirement |
| GPT-4o / Claude | ~90%+ | Slow/expensive | Low-volume, complex reasoning |
| Qwen 2.5 (local) | ~83% | Fast (local) | Privacy-sensitive, no API cost |

## Common Mistakes

1. **Using generic BERT** — general sentiment models underperform on financial text; use FinBERT
2. **No signal decay** — old news should have diminishing impact; apply exponential decay
3. **Ignoring negation** — "not bullish" is bearish; FinBERT handles this, but verify
4. **Processing titles only** — article body often contradicts headline; process full text
5. **No source weighting** — Reuters carries more weight than anonymous Twitter; weight accordingly
6. **Treating neutral as zero** — "neutral" often means "uncertainty", which is itself a signal

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using generic BERT/GPT for financial sentiment | General models misclassify financial language ("downgrade" is negative in finance, neutral elsewhere) | Use FinBERT or finance-fine-tuned models; validate on Financial PhraseBank dataset before deployment |
| Processing only headlines, ignoring article body | Headlines are clickbait-optimised; body often contradicts or qualifies the headline sentiment | Process full article text; weight body content higher than headline for sentiment scoring |
| No signal decay on old sentiment data | Week-old news still influencing trading signals long after the market has priced it in | Apply exponential decay (half-life 4-24 hours for news, longer for earnings); weight recency |
| Equal weighting of all sources | Anonymous Twitter carries same weight as Reuters; noise overwhelms signal | Implement source credibility scoring; weight established financial media higher than social media |
| Treating neutral sentiment as zero signal | "Neutral" often indicates uncertainty or disagreement, which itself correlates with increased volatility | Model neutral as a separate signal class; map to volatility expectations rather than directional bias |

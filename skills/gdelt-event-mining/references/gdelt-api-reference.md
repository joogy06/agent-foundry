# GDELT API Reference — Endpoints, Query Syntax, Schemas

## Doc API 2.0 (Primary)

Base: `https://api.gdeltproject.org/api/v2/doc/doc`

### Query parameters

| Param | Purpose | Example |
|---|---|---|
| `query` | Full-text + filter expression | `theme:ECON_TAXATION sourcelang:eng` |
| `mode` | Response shape | `ArtList`, `TimelineVolInfo`, `ToneChart`, `WordCloudEnglish` |
| `format` | Serialization | `json`, `jsonfeed`, `csv`, `html` |
| `timespan` | Time window (backward) | `7days`, `1week`, `24hours`, `1month` |
| `startdatetime` | Explicit start (UTC) | `20260401000000` |
| `enddatetime` | Explicit end (UTC) | `20260408235959` |
| `sort` | Result ordering | `DateDesc`, `DateAsc`, `ToneDesc`, `ToneAsc`, `Hybrid`, `HybridRel` |
| `maxrecords` | Cap result count | `250` (API max per call) |

### Query operators

| Operator | Purpose | Example |
|---|---|---|
| `theme:<CODE>` | Filter by V2Theme | `theme:ECON_INTEREST_RATES` |
| `sourcelang:<ISO>` | Filter by language | `sourcelang:eng` |
| `sourcecountry:<ISO>` | Filter by source country | `sourcecountry:US` |
| `tone<N`, `tone>N` | Filter by tone | `tone<-5` (negative tone) |
| `domainis:<domain>` | Filter to specific source | `domainis:reuters.com` |
| `"phrase"` | Exact phrase | `"interest rate cut"` |
| `(A OR B)` | Boolean | `(theme:ECON_TAXATION OR theme:LEG_REGULATORY)` |
| `-` | Exclusion | `theme:ECON_TAXATION -theme:WB_2973_FINANCIAL_INCLUSION` |

### Example queries

Economic taxation events in the US, last 7 days:
```
https://api.gdeltproject.org/api/v2/doc/doc?query=theme:ECON_TAXATION%20sourcecountry:US&mode=ArtList&format=json&timespan=7days&maxrecords=100
```

Negative-tone crypto regulation events globally, last month:
```
https://api.gdeltproject.org/api/v2/doc/doc?query=theme:ECON_CRYPTO%20theme:LEG_REGULATORY%20tone<-3&mode=ArtList&format=json&timespan=1month&maxrecords=250
```

Volume over time for a theme (for velocity computation):
```
https://api.gdeltproject.org/api/v2/doc/doc?query=theme:ECON_TAXATION&mode=TimelineVolInfo&format=json&timespan=30days
```

### Response schema (ArtList mode)

```json
{
  "articles": [
    {
      "url": "https://example.com/story",
      "url_mobile": "",
      "title": "Story title",
      "seendate": "20260411T143000Z",
      "socialimage": "https://...",
      "domain": "example.com",
      "language": "English",
      "sourcecountry": "United States"
    }
  ]
}
```

Note: ArtList does NOT include CAMEO event codes or actor fields — those come from the Events 2.0
CSV dumps. ArtList is faster and sufficient for most founder-ideation use cases (theme velocity,
headline extraction).

### Response schema (TimelineVolInfo mode)

```json
{
  "timeline": [
    {
      "series": "Volume Intensity",
      "data": [
        {"date": "20260401", "value": 0.012},
        {"date": "20260402", "value": 0.018}
      ]
    }
  ]
}
```

Values are normalized proportions of total news volume, not absolute counts.

---

## GKG 2.1 (Global Knowledge Graph)

Download URL pattern:
```
http://data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.gkg.csv.zip
```

Updates every 15 minutes. Each file is a CSV with columns: `GKGRECORDID`, `V2.1DATE`,
`V2SOURCECOLLECTIONIDENTIFIER`, `V2SOURCECOMMONNAME`, `V2DOCUMENTIDENTIFIER`, `V1COUNTS`,
`V2.1COUNTS`, `V1THEMES`, `V2ENHANCEDTHEMES`, `V1LOCATIONS`, `V2ENHANCEDLOCATIONS`, `V1PERSONS`,
`V2ENHANCEDPERSONS`, `V1ORGANIZATIONS`, `V2ENHANCEDORGANIZATIONS`, `V1.5TONE`,
`V2.1ENHANCEDDATES`, `V2GCAM`, `V2.1SHARINGIMAGE`, `V2.1RELATEDIMAGES`, `V2.1SOCIALIMAGEEMBEDS`,
`V2.1SOCIALVIDEOEMBEDS`, `V2.1QUOTATIONS`, `V2.1ALLNAMES`, `V2.1AMOUNTS`, `V2.1TRANSLATIONINFO`,
`V2EXTRASXML`.

Use GKG when the caller needs:
- Full entity extraction (people, orgs mentioned)
- Quotations from articles
- Dates referenced in articles
- Amounts (money, counts) extracted from text

For founder-ideation's trend-first team, ArtList + TimelineVolInfo from Doc API is usually
sufficient. GKG is Phase 2+ territory.

---

## Events 2.0 (Structured Event Records)

Download URL pattern:
```
http://data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.export.CSV.zip
```

Columns (58 total): `GLOBALEVENTID`, `SQLDATE`, `MonthYear`, `Year`, `FractionDate`,
`Actor1Code`, `Actor1Name`, `Actor1CountryCode`, `Actor1KnownGroupCode`, `Actor1EthnicCode`,
`Actor1Religion1Code`, `Actor1Religion2Code`, `Actor1Type1Code`, `Actor1Type2Code`, `Actor1Type3Code`,
`Actor2Code`, ... (same for Actor2), `IsRootEvent`, `EventCode`, `EventBaseCode`, `EventRootCode`,
`QuadClass`, `GoldsteinScale`, `NumMentions`, `NumSources`, `NumArticles`, `AvgTone`,
`Actor1Geo_Type`, `Actor1Geo_FullName`, `Actor1Geo_CountryCode`, `Actor1Geo_ADM1Code`,
`Actor1Geo_Lat`, `Actor1Geo_Long`, `Actor1Geo_FeatureID`, `Actor2Geo_*`, `ActionGeo_*`,
`DATEADDED`, `SOURCEURL`.

Use Events 2.0 when the caller needs CAMEO event code grounding (e.g., "which events were
specifically 'announce policy change'?" — that's EventCode 051).

---

## Rate Limits (observed)

GDELT publishes limited rate-limit documentation. Observed behavior (ported from trading wiki):
- Doc API: ~1 request per 5 seconds sustained is usually fine
- Heavier queries (large `maxrecords`, broad `query`) get 429'd faster
- The CSV dumps (GKG, Events) have no per-request rate limit but bandwidth is limited
- Busy global news days (major events) increase 429 frequency

Best practice: single request every 5s, exponential backoff on 429, circuit breaker at 3
consecutive failures.

---

## Useful Static Data URLs

- V2Themes catalog: `http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT`
- V1 CAMEO events: `http://gdeltproject.org/data/lookups/CAMEO.eventcodes.txt`
- CAMEO actor codes: `http://gdeltproject.org/data/lookups/CAMEO.type.txt`
- Country codes: `http://gdeltproject.org/data/lookups/CAMEO.country.txt`

Download these once, cache locally — they drift slowly (months, not days).

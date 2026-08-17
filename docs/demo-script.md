# OnRecord demo script

**Runtime: about 5 minutes 30 seconds at a steady pace.** A 90 second short
version is marked at the bottom.

One browser tab the whole time:
`https://onrecord-production-842c.up.railway.app`

Every number in the spoken lines was measured live on 2026-08-17 against the
production app. Numbers that can drift before you hit record carry a bracketed
reminder. Re-check those with the pre-flight block below.

---

## 0. Pre-flight (do this 10 minutes before recording)

**Do not deploy anything today.** A push to Railway restarts the service and
throws away the warm index. A cold first query can take 30 seconds or more, on
camera, with no way to explain it. Freeze the repo until the video is uploaded.

### Step 1: confirm the headline numbers still match

```bash
B=https://onrecord-production-842c.up.railway.app

# 309,662 documents, corpus v3, 51 jurisdictions, 295 tickers
curl -s "$B/api/stats"

# 7 scoreboard rows, first is v1-bool at 0.000, latest is v3-3L at 0.521
curl -s "$B/api/metrics" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d),'rows'); [print(r['corpus_version'], round(r['metrics']['mean']['NDCG@10'],3)) for r in d]"

# 1,527 verbatim commitments
curl -s "$B/api/promises?limit=1" | python3 -c "import json,sys; print(json.load(sys.stdin)['total'])"

# 493 followed up, 780 gone quiet
curl -s "$B/api/outcomes/summary" | python3 -c "import json,sys; print(json.load(sys.stdin)['statuses'])"

# 66,383 MW promised, 68,679 jobs, $233.9B
curl -s "$B/api/promised" | python3 -c "import json,sys; r=json.load(sys.stdin)['rollups']; print(round(sum(v['promised_mw'] for v in r.values())), 'MW |', round(sum(v['promised_jobs'] for v in r.values())), 'jobs | $%.1fB' % (sum(v['promised_dollars_total'] for v in r.values())/1e9))"

# 11,800 MW filed, sources miso spp ercot caiso
curl -s "$B/api/grid" | python3 -c "import json,sys; d=json.load(sys.stdin); print(round(sum(v['queued_mw'] for v in d['by_jurisdiction'].values())), 'MW |', d['sources'])"
```

If any figure differs from the script, say the figure on your screen. The screen
wins. Never read a number the app can contradict while you are pointing at it.

### Step 2: warm every path you will touch

Run each of these twice. The second run is the warm one, which is what the
viewer will see.

```bash
for m in lexical semantic hybrid; do
  time curl -s -o /dev/null "$B/api/search?q=how+much+water+does+a+data+center+use&mode=$m&k=10"
done

# warms the answer path (measured 13.1s) and the refusal path (measured 4.0s)
curl -s -X POST "$B/api/answer" -H 'content-type: application/json' \
  -d '{"question":"How much water does a data center use?"}' -o /dev/null
curl -s -X POST "$B/api/answer" -H 'content-type: application/json' \
  -d '{"question":"What will Nvidia stock be worth in 2027?"}' -o /dev/null
```

Expected warm timings, measured today: lexical about 2 seconds, semantic about
4 to 5 seconds, hybrid about 5 to 6 seconds, a grounded answer about 13
seconds, a refusal about 4 seconds.

### Step 3: open the tab and click through once

Load Search, Ask, Tickers, Scoreboard, Ledger once each before you record. Then
reload to Search and start.

### If something is slow on camera

Say this, plainly, and keep going:

> "Semantic and hybrid take a few seconds here. That is a real vector search
> over three hundred thousand documents on one small box. I would rather show
> you the honest latency than a cached screenshot."

---

## 1. Cold open: a real question, real receipts (0:00 to 0:50)

**Do:** Start on the Search tab. Click the **Hybrid** mode pill. Type
`how much water does a data center use` and press enter. Let the results land.

**On screen:** Five to ten result cards. Top results include Maricopa County AZ,
Cheyenne WY, and Bartow County GA. Each card carries a jurisdiction, a date, a
SWORN venue tag, and a timestamp link.

**Say:**

> "This is OnRecord. It is a search engine over the public record of the AI
> datacenter buildout. Three hundred nine thousand, six hundred sixty two
> documents. County meeting transcripts, city council agenda records, and SEC
> filings, across fifty one jurisdictions.
>
> I asked how much water a data center uses. Look at what came back. This is a
> county planning hearing in Maricopa County, Arizona. This one is Cheyenne,
> Wyoming. This one is Bartow County, Georgia. Each of these is a real person
> answering that question, under oath, in a public meeting, on a date you can
> check."

*[Re-check: the document count is on the header of the Search tab. Read whatever
it says.]*

---

## 2. The receipt (0:50 to 1:15)

**Do:** Click the timestamp link on the **Bartow County, GA** card (verified
live today: `youtube.com/watch?v=aE1TeEUwWCc&t=3600s`). The video opens at 1:00:00.
Let two or three seconds of audio play. Come back to the tab.

**On screen:** A county commission meeting. A resident asks the question the
snippet quoted.

**Say:**

> "That is the whole idea. The snippet said 'how much water does a data center
> use daily'. The link opens the meeting at the second that sentence was spoken.
> Every result in this app carries a link like that. You can always go check me."

*[Re-check: run the pre-flight search once and confirm the Bartow card is still
in the top five. If it moved, use whichever card is highest with a timestamp
link.]*

---

## 3. Three retrieval modes (1:15 to 1:40)

**Do:** Click **Lexical**, then **Semantic**, then back to **Hybrid**. Do not
retype the query.

**Say:**

> "Three retrieval modes, all live. Lexical is my own inverted index with BM25
> scoring, written from scratch. Semantic is dense vector retrieval over the
> whole corpus. Hybrid fuses the two with reciprocal rank fusion. Lexical comes
> back in about two seconds. Semantic and hybrid take four to six. That is the
> real cost of vector search at this scale, and I am showing it to you rather
> than hiding it."

---

## 4. The Promise Ledger (1:40 to 2:45)

**Do:** Click **Ledger** in the top navigation. Point at the four stat cards
across the top, then scroll to the promise rows.

**On screen:** Cards reading ON THE RECORD 1,527; PROMISED 66,383 MW;
FOLLOWED UP 493; IN THE GRID QUEUE 11,800 MW. Below them, promise rows with
verbatim quotes and outcome tags reading FOLLOWED UP IN THE RECORD or
NO FURTHER MENTION IN THE RECORD.

**Say:**

> "This is the part I care about most. Search finds a document. The ledger
> follows what somebody promised.
>
> One thousand five hundred twenty seven commitments, pulled out of the record
> as verbatim quotes. Every extraction has to be an exact substring of its source
> document, enforced in code, or it gets dropped.
>
> Add up what those commitments quantify. Sixty six thousand three hundred
> eighty three megawatts. Sixty eight thousand six hundred seventy nine jobs.
> Two hundred thirty three point nine billion dollars pledged.
>
> Then the third card. Four hundred ninety three of those promises show up again
> later in the record. Seven hundred eighty have gone quiet. Both of those
> numbers come with receipts on both ends."

**Do:** Scroll to a quantified row with a follow-up trail. Verified live today:
Richland Parish, LA, dated 2026-08-03, quoting a fifty billion dollar
investment, with a two step trail. San Antonio, TX has several with longer
trails.

**Say:**

> "Here is one. Richland Parish, Louisiana. Fifty billion dollars into a data
> center, said out loud in a meeting. The trail underneath shows where the later
> record picked it back up. When there is no trail, the row says so. The app
> reports the gap. It does not accuse anyone."

**Do:** Point at the grid queue card.

**Say:**

> "The last card is different in kind, so it lives on its own line. Eleven
> thousand eight hundred megawatts sitting in interconnection queues at four
> grid operators. MISO, SPP, ERCOT, and CAISO. Filing a queue request is one
> act. Promising a county something is another act. The ledger keeps them apart
> on purpose."

*[Re-check: all four card values come straight from the endpoints in the
pre-flight block. Read the cards on screen. This page is only a backup.]*

---

## 5. Ask, with citations (2:45 to 3:35)

**Do:** Click **Ask**. Type `How much water does a data center use?` and submit.
It takes about 13 seconds. Talk through the wait using the first paragraph
below.

**On screen:** A short answer with numbered green citation chips inline. Eight
citations. A grounding line. Hovering a chip pops the source snippet with its
venue tag and date.

**Say (while it runs):**

> "Ask does retrieval augmented generation over the same corpus. It retrieves,
> then it writes an answer, then a second model checks every claim in that answer
> against the retrieved text. That takes about thirteen seconds and I am not
> going to cut it out."

**Say (when the answer lands, hovering one citation chip):**

> "Every claim carries a numbered chip. Hover one and you get the source snippet,
> the venue, and the date. Click it and you are back at the timestamp in the
> meeting.
>
> Read the grounding line. It tells you how many claims the checker could trace
> to a citation and how many it could not. On my last run that read eight of
> nine. The app tells you when it is partly grounded instead of quietly rounding
> up."

*[Re-check: this is a live model call, so the citation count and the grounding
line will differ run to run. Read what is on your screen. If it says partial,
say partial. That is the point.]*

**On the measured evaluation, over the answer:**

> "I measured this. Faithfulness scored zero point nine three zero across a
> judged evaluation set, using a judge I validated at zero point nine four four
> agreement against labeled claims."

---

## 6. The refusal (3:35 to 3:55)

**Do:** Ask `What will Nvidia stock be worth in 2027?`. It comes back in about
four seconds.

**On screen:** A refusal message with suggested reformulations. Zero citations.

**Say:**

> "Now watch what happens when the record cannot answer. It refuses, and it tells
> you why, and it suggests a better question. Twelve out of twelve unanswerable
> questions were correctly refused in my evaluation. Zero answerable questions
> were falsely refused."

---

## 7. The scoreboard (3:55 to 4:40)

**Do:** Click **Scoreboard**. Point at the top row, then the bottom row.

**On screen:** Seven rows. The first is v1-bool with 0.000 across the board. The
last is v3-3L with NDCG at 10 of 0.521.

**Say:**

> "This page is the argument. You cannot judge a retrieval system by reading its
> output. You need labels.
>
> Top row. Boolean matching, day one, no ranking at all. NDCG of zero point zero
> zero zero. The relevant documents are in there. They are buried under thousands
> of matches. That is the honest starting line, and I left it on the board.
>
> Bottom row. Corpus version three, current deployment. NDCG at ten of zero point
> five two one. Seven rows between them, including the runs that went down. One
> of those rows dropped when I repaired a pooling bias in my own judgment set. I
> kept the old reading and the repaired one side by side.
>
> Under it: four thousand six hundred seventy three relevance judgments, across
> one hundred queries, from six labeling sessions. The deployment gate reads pass.
> Semantic zero point five two one. Hybrid zero point five zero zero. Lexical
> zero point four four four."

*[Re-check: the pre-flight metrics command prints all seven rows. Confirm the
count is still seven and the last row still reads 0.521.]*

---

## 8. The rest of the surface, fast (4:40 to 5:10)

**Do:** Click **Tickers**. Open one with data (VST or a large utility). Scroll
the detail pane past the price chart, the Form 4 conduct panel, and the 8-K
material events panel. Then click **Ledger** and scroll to the Dodge Index.
Then point at the Hearings on air panel at the top of the page.

**Say:**

> "Quickly, the rest. Two hundred ninety five tickers, each one anchored to the
> moments it gets mentioned in the record. Insider transactions from Form 4
> filings. Material events typed from 8-K item codes.
>
> The Dodge Index counts explicit deferral phrases per thousand meeting
> documents. Phrases like 'no comment' and 'get back to you', from a frozen
> public word list. No model touches that score, so it reproduces exactly.
>
> And the app tracks upcoming public hearings across all fifty one jurisdictions,
> with a watch link, so the corpus keeps growing from the meetings that have not
> happened yet."

*[Re-check: the Hearings panel shows anything currently on air first, then
upcoming. When I checked, nothing was live and six upcoming hearings were
listed. Do not promise a live stream unless you see one.]*

---

## 9. Close: what I did not build (5:10 to 5:30)

**Do:** Return to the Search tab. Stop scrolling. Look at the camera.

**Say:**

> "Two things I deliberately did not build.
>
> There are no trade signals and no investment advice anywhere in this app. The
> portfolio lens is read only. It shows you what the public record says about
> the things you already hold, and it stops there.
>
> And the letter drafting module cannot mail anything on its own. The send
> function refuses by default. It raises a consent error before it touches the
> network, and there is no batch path in the code. A human confirms every single
> letter.
>
> Sixty six tickets. One thousand four hundred seventy two tests. A full census
> of every video receipt put link rot at zero point nine eight percent. About
> thirty three dollars of external AI spend for the whole project. This is
> OnRecord."

*[Re-check the spend figure against `docs/cost-analysis.md` before recording.
The repo authority reads about thirty three dollars. If you have a newer running
total, say that number instead.]*

---

## Short version (90 seconds)

Use beats 1, 4, 5, and 9. Cut everything else.

**0:00 to 0:25.** Search tab, hybrid mode, type
`how much water does a data center use`, click the Bartow County timestamp link.

> "OnRecord searches three hundred nine thousand documents of public record on
> the AI datacenter buildout. County hearings, council records, SEC filings. That
> link opens the meeting at the second the sentence was spoken. Every result
> works like that."

**0:25 to 0:55.** Ledger tab. Point at the four stat cards.

> "One thousand five hundred twenty seven commitments, extracted as verbatim
> quotes. Sixty six thousand megawatts promised. Sixty eight thousand jobs. Two
> hundred thirty three point nine billion dollars. Four hundred ninety three of
> those promises resurface later in the record. Seven hundred eighty have gone
> quiet."

**0:55 to 1:20.** Ask tab, submit the pre-warmed water question, hover a
citation chip.

> "Ask writes an answer from those documents and checks every claim against the
> sources. Faithfulness measured at zero point nine three zero. Twelve out of
> twelve unanswerable questions refused. Zero false refusals. Every chip is a
> link back to a hearing."

**1:20 to 1:30.** Scoreboard tab, point at the first and last rows.

> "Seven measured runs. The first is boolean matching at zero point zero zero
> zero. The current deployment is zero point five two one. I kept every row,
> including the ones that went down."

---

## Verified figures cheat sheet

| Figure | Value | Source checked |
|---|---|---|
| Documents | 309,662 (corpus v3) | `/api/stats` |
| Sources | 289,882 county meeting / 18,337 legistar / 1,443 filing | `/api/stats` |
| Jurisdictions | 51 | `/api/stats` |
| Tickers | 295 | `/api/stats` |
| Warm latency | lexical ~2.0s, semantic ~4.3s, hybrid ~5.3s | timed `curl` |
| Grounded answer latency | ~13.1s | timed `POST /api/answer` |
| Refusal latency | ~4.0s | timed `POST /api/answer` |
| Scoreboard rows | 7, first 0.000, last 0.521 | `/api/metrics` |
| Deployment gate | PASS, semantic 0.521 / hybrid 0.500 / lexical 0.444 | `docs/metrics.md` |
| Judgments | 4,673 rows, 100 queries, six sessions | `docs/metrics.md` |
| Faithfulness | 0.930, 12 of 12 refused, 0 false refusals | `docs/metrics.md` |
| Judge agreement | 0.944 | `docs/metrics.md` |
| Commitments | 1,527 | `/api/promises` |
| Promised totals | 66,383 MW / 68,679 jobs / $233.9B | `/api/promised` |
| Outcomes | 493 followed up / 780 gone quiet | `/api/outcomes/summary` |
| Grid queue | 11,800 MW, MISO SPP ERCOT CAISO | `/api/grid` |
| Dodge Index | 45 jurisdictions scored | `/api/dodge` |
| Tests | 1,472 collected | `pytest --collect-only` |
| Tickets | 66 | `tickets/` |
| Link rot | 0.98% | `docs/metrics.md` |
| External AI spend | about $33 | `docs/cost-analysis.md` |
